use encoding_rs::{SHIFT_JIS, UTF_16BE, UTF_16LE, UTF_8};
use globset::{Glob, GlobSet, GlobSetBuilder};
use rayon::prelude::*;
use regex::{Regex, RegexBuilder};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeSet, HashMap, HashSet};
use std::env;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use walkdir::{DirEntry, WalkDir};

const MAX_FILE_BYTES: u64 = 5 * 1024 * 1024;

#[derive(Debug, Deserialize)]
struct SearchRequest {
    project_path: Option<String>,
    include_patterns: Vec<String>,
    exclude_patterns: Vec<String>,
    query: SearchQuery,
    open_editors: Vec<OpenEditor>,
    ignored_occurrences: Vec<IgnoredOccurrence>,
}

#[derive(Debug, Deserialize)]
struct SearchQuery {
    search_text: String,
    match_case: bool,
    use_regex: bool,
    whole_word: bool,
    regex_pattern: String,
}

#[derive(Debug, Deserialize)]
struct OpenEditor {
    path: String,
    content: String,
}

#[derive(Debug, Deserialize)]
struct IgnoredOccurrence {
    path: String,
    line_number: usize,
    pos: usize,
    length: usize,
    line_text: String,
}

#[derive(Debug, Serialize)]
struct SearchResponse {
    files_found: usize,
    matches_found: usize,
    files: Vec<FileResult>,
}

#[derive(Debug, Serialize)]
struct FileResult {
    path: String,
    occurrences: Vec<Occurrence>,
}

#[derive(Debug, Clone, Serialize)]
struct Occurrence {
    line_number: usize,
    line_text: String,
    display_text: String,
    tooltip_text: String,
    pos: usize,
    length: usize,
    encoding: String,
}

struct PatternFilters {
    include: GlobSet,
    exclude: GlobSet,
    has_include: bool,
}

impl PatternFilters {
    fn new(include_patterns: &[String], exclude_patterns: &[String]) -> Result<Self, String> {
        Ok(Self {
            include: build_glob_set(include_patterns)?,
            exclude: build_glob_set(exclude_patterns)?,
            has_include: !include_patterns.is_empty(),
        })
    }

    fn include_file(&self, path: &str) -> bool {
        let name = Path::new(path)
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or(path);
        !self.exclude.is_match(name) && (!self.has_include || self.include.is_match(name))
    }

    fn include_dir_entry(&self, entry: &DirEntry) -> bool {
        let name = entry.file_name().to_string_lossy();
        !entry.file_type().is_dir() || !self.exclude.is_match(name.as_ref())
    }
}

fn build_glob_set(patterns: &[String]) -> Result<GlobSet, String> {
    let mut builder = GlobSetBuilder::new();
    for pattern in patterns {
        builder.add(Glob::new(pattern).map_err(|error| format!("invalid glob pattern {pattern}: {error}"))?);
    }
    builder.build().map_err(|error| error.to_string())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), String> {
    let args: Vec<String> = env::args().collect();
    if args.len() != 5 || args[1] != "--request" || args[3] != "--response" {
        return Err("usage: project_search_worker --request <request.json> --response <response.json>".to_string());
    }

    let request_text = fs::read_to_string(&args[2]).map_err(|error| format!("cannot read request file: {error}"))?;
    let request: SearchRequest = serde_json::from_str(&request_text).map_err(|error| format!("invalid request json: {error}"))?;
    let response = search_project(request)?;
    let response_text = serde_json::to_string(&response).map_err(|error| format!("cannot serialize response json: {error}"))?;
    fs::write(&args[4], response_text).map_err(|error| format!("cannot write response file: {error}"))?;
    Ok(())
}

fn search_project(request: SearchRequest) -> Result<SearchResponse, String> {
    let filters = PatternFilters::new(&request.include_patterns, &request.exclude_patterns)?;
    let regex = compile_regex(&request.query)?;
    let open_editors: HashMap<String, String> = request
        .open_editors
        .into_iter()
        .map(|editor| (normalize_path_text(&editor.path), editor.content))
        .collect();
    let ignored = ignored_set(request.ignored_occurrences);
    let target_files = collect_target_files(request.project_path.as_deref(), &open_editors, &filters);

    let mut files: Vec<FileResult> = target_files
        .par_iter()
        .filter_map(|path| search_file(path, open_editors.get(path), &regex, &ignored))
        .collect();
    files.sort_by(|left, right| left.path.to_lowercase().cmp(&right.path.to_lowercase()));

    let matches_found = files.iter().map(|file| file.occurrences.len()).sum();
    Ok(SearchResponse {
        files_found: files.len(),
        matches_found,
        files,
    })
}

fn collect_target_files(project_path: Option<&str>, open_editors: &HashMap<String, String>, filters: &PatternFilters) -> Vec<String> {
    let mut files = BTreeSet::new();

    if let Some(project_path) = project_path {
        let root = PathBuf::from(project_path);
        let walker = WalkDir::new(root).into_iter().filter_entry(|entry| filters.include_dir_entry(entry));
        for entry in walker.filter_map(Result::ok) {
            if entry.file_type().is_file() {
                let path = normalize_path(entry.path());
                if filters.include_file(&path) {
                    files.insert(path);
                }
            }
        }
    }

    for path in open_editors.keys() {
        if filters.include_file(path) {
            files.insert(path.clone());
        }
    }

    files.into_iter().collect()
}

fn search_file(
    path: &str,
    open_content: Option<&String>,
    regex: &Regex,
    ignored: &HashSet<String>,
) -> Option<FileResult> {
    let (text, encoding) = match open_content {
        Some(content) => (content.clone(), "utf-8".to_string()),
        None => read_text_file(Path::new(path)).ok()?,
    };

    let mut occurrences = search_text(&text, &encoding, regex);
    occurrences.retain(|occurrence| !ignored.contains(&occurrence_key(path, occurrence)));
    if occurrences.is_empty() {
        None
    } else {
        Some(FileResult {
            path: path.to_string(),
            occurrences,
        })
    }
}

fn compile_regex(query: &SearchQuery) -> Result<Regex, String> {
    let pattern = if query.use_regex {
        query.regex_pattern.clone()
    } else if query.whole_word {
        format!(r"\b{}\b", regex::escape(&query.search_text))
    } else {
        regex::escape(&query.search_text)
    };

    RegexBuilder::new(&pattern)
        .case_insensitive(!query.match_case)
        .build()
        .map_err(|error| format!("invalid regex: {error}"))
}

fn search_text(text: &str, encoding: &str, regex: &Regex) -> Vec<Occurrence> {
    let mut occurrences = Vec::new();
    for (line_index, line) in split_lines(text).enumerate() {
        for matched in regex.find_iter(line) {
            occurrences.push(make_occurrence(
                line_index + 1,
                line,
                matched.start(),
                matched.end(),
                encoding,
            ));
        }
    }
    occurrences
}

fn split_lines(text: &str) -> impl Iterator<Item = &str> {
    text.split('\n').map(|line| line.strip_suffix('\r').unwrap_or(line))
}

fn make_occurrence(line_number: usize, line: &str, byte_pos: usize, byte_end: usize, encoding: &str) -> Occurrence {
    let pos = line[..byte_pos].chars().count();
    let length = line[byte_pos..byte_end].chars().count();
    let trimmed_line = line.trim();
    Occurrence {
        line_number,
        line_text: line.to_string(),
        display_text: format!("{line_number}: {trimmed_line}"),
        tooltip_text: line.to_string(),
        pos,
        length,
        encoding: encoding.to_string(),
    }
}

fn read_text_file(path: &Path) -> io::Result<(String, String)> {
    let metadata = fs::metadata(path)?;
    if metadata.len() > MAX_FILE_BYTES {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "file is too large"));
    }

    let raw = fs::read(path)?;
    if raw.contains(&0) && !(raw.starts_with(&[0xff, 0xfe]) || raw.starts_with(&[0xfe, 0xff])) {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "binary file"));
    }

    if raw.starts_with(&[0xef, 0xbb, 0xbf]) {
        let (text, _, _) = UTF_8.decode(&raw[3..]);
        return Ok((text.into_owned(), "utf-8-sig".to_string()));
    }
    if raw.starts_with(&[0xff, 0xfe]) {
        let (text, _, _) = UTF_16LE.decode(&raw[2..]);
        return Ok((text.into_owned(), "utf-16-le".to_string()));
    }
    if raw.starts_with(&[0xfe, 0xff]) {
        let (text, _, _) = UTF_16BE.decode(&raw[2..]);
        return Ok((text.into_owned(), "utf-16-be".to_string()));
    }

    let (utf8_text, _, had_errors) = UTF_8.decode(&raw);
    if !had_errors {
        return Ok((utf8_text.into_owned(), "utf-8".to_string()));
    }

    let (text, _, _) = SHIFT_JIS.decode(&raw);
    Ok((text.into_owned(), "cp932".to_string()))
}

fn ignored_set(ignored_occurrences: Vec<IgnoredOccurrence>) -> HashSet<String> {
    ignored_occurrences
        .into_iter()
        .map(|occurrence| {
            let path = occurrence.path;
            let occurrence_data = Occurrence {
                line_number: occurrence.line_number,
                line_text: occurrence.line_text,
                display_text: String::new(),
                tooltip_text: String::new(),
                pos: occurrence.pos,
                length: occurrence.length,
                encoding: String::new(),
            };
            occurrence_key(&path, &occurrence_data)
        })
        .collect()
}

fn occurrence_key(path: &str, occurrence: &Occurrence) -> String {
    format!(
        "{}\u{1f}{}\u{1f}{}\u{1f}{}\u{1f}{}",
        normalize_path_text(path),
        occurrence.line_number,
        occurrence.pos,
        occurrence.length,
        occurrence.line_text
    )
}

fn normalize_path(path: &Path) -> String {
    normalize_path_text(&path.to_string_lossy())
}

fn normalize_path_text(path: &str) -> String {
    path.replace('/', "\\")
}
