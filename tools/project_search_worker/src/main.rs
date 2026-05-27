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

fn default_operation() -> String {
    "search".to_string()
}

#[derive(Debug, Deserialize)]
struct SearchRequest {
    #[serde(default = "default_operation")]
    operation: String,
    project_path: Option<String>,
    #[serde(default)]
    include_patterns: Vec<String>,
    #[serde(default)]
    exclude_patterns: Vec<String>,
    query: SearchQuery,
    #[serde(default)]
    open_editors: Vec<OpenEditor>,
    #[serde(default)]
    ignored_occurrences: Vec<IgnoredOccurrence>,
    #[serde(default)]
    replace_text: String,
    #[serde(default)]
    targets: Vec<ReplaceTarget>,
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
    #[serde(default)]
    dirty: bool,
    #[serde(default)]
    encoding: Option<String>,
}

#[derive(Debug, Deserialize)]
struct IgnoredOccurrence {
    path: String,
    line_number: usize,
    pos: usize,
    length: usize,
    line_text: String,
}

#[derive(Debug, Deserialize)]
struct ReplaceTarget {
    path: String,
    occurrences: Vec<ReplaceOccurrence>,
}

#[derive(Debug, Clone, Deserialize)]
struct ReplaceOccurrence {
    line_number: usize,
    pos: usize,
    length: usize,
}

#[derive(Debug, Serialize)]
struct SearchResponse {
    operation: String,
    files_found: usize,
    matches_found: usize,
    replaced_files: usize,
    replaced_count: usize,
    files: Vec<FileResult>,
    updated_open_editors: Vec<UpdatedOpenEditor>,
    saved_files: Vec<String>,
    failed_files: Vec<FailedFile>,
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

#[derive(Debug, Serialize)]
struct UpdatedOpenEditor {
    path: String,
    new_text: String,
    dirty: bool,
    saved: bool,
    encoding: String,
}

#[derive(Debug, Serialize)]
struct FailedFile {
    path: String,
    error: String,
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
    let response = match request.operation.as_str() {
        "search" => search_project(request)?,
        "replace" => replace_targets(request),
        operation => return Err(format!("unknown operation: {operation}")),
    };
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
        operation: "search".to_string(),
        files_found: files.len(),
        matches_found,
        replaced_files: 0,
        replaced_count: 0,
        files,
        updated_open_editors: Vec::new(),
        saved_files: Vec::new(),
        failed_files: Vec::new(),
    })
}

fn replace_targets(request: SearchRequest) -> SearchResponse {
    let open_editors: HashMap<String, OpenEditor> = request
        .open_editors
        .into_iter()
        .map(|editor| (normalize_path_text(&editor.path), editor))
        .collect();

    let replace_text = request.replace_text;
    let mut replaced_files = 0;
    let mut replaced_count = 0;
    let mut updated_open_editors = Vec::new();
    let mut saved_files = Vec::new();
    let mut failed_files = Vec::new();

    for target in request.targets {
        let path = normalize_path_text(&target.path);
        let result = replace_one_target(&path, &target.occurrences, &replace_text, open_editors.get(&path));
        match result {
            Ok(replace_result) => {
                if replace_result.replaced_count == 0 {
                    continue;
                }
                replaced_files += 1;
                replaced_count += replace_result.replaced_count;
                if let Some(updated_editor) = replace_result.updated_open_editor {
                    updated_open_editors.push(updated_editor);
                }
                if let Some(saved_file) = replace_result.saved_file {
                    saved_files.push(saved_file);
                }
            }
            Err(error) => failed_files.push(FailedFile { path, error }),
        }
    }

    SearchResponse {
        operation: "replace".to_string(),
        files_found: 0,
        matches_found: 0,
        replaced_files,
        replaced_count,
        files: Vec::new(),
        updated_open_editors,
        saved_files,
        failed_files,
    }
}

struct ReplaceOneResult {
    replaced_count: usize,
    updated_open_editor: Option<UpdatedOpenEditor>,
    saved_file: Option<String>,
}

fn replace_one_target(
    path: &str,
    occurrences: &[ReplaceOccurrence],
    replace_text: &str,
    open_editor: Option<&OpenEditor>,
) -> Result<ReplaceOneResult, String> {
    let (text, encoding, dirty) = match open_editor {
        Some(editor) => (
            editor.content.clone(),
            editor.encoding.clone().unwrap_or_else(|| "utf-8".to_string()),
            editor.dirty,
        ),
        None => {
            let (text, encoding) = read_text_file(Path::new(path)).map_err(|error| error.to_string())?;
            (text, encoding, false)
        }
    };

    let (new_text, replaced_count) = replace_occurrences_in_text(&text, occurrences, replace_text);
    if replaced_count == 0 {
        return Ok(ReplaceOneResult {
            replaced_count: 0,
            updated_open_editor: None,
            saved_file: None,
        });
    }

    if let Some(_editor) = open_editor {
        let saved = !dirty;
        if saved {
            write_text_file(Path::new(path), &new_text, &encoding).map_err(|error| error.to_string())?;
        }
        Ok(ReplaceOneResult {
            replaced_count,
            updated_open_editor: Some(UpdatedOpenEditor {
                path: path.to_string(),
                new_text,
                dirty,
                saved,
                encoding,
            }),
            saved_file: if saved { Some(path.to_string()) } else { None },
        })
    } else {
        write_text_file(Path::new(path), &new_text, &encoding).map_err(|error| error.to_string())?;
        Ok(ReplaceOneResult {
            replaced_count,
            updated_open_editor: None,
            saved_file: Some(path.to_string()),
        })
    }
}

fn replace_occurrences_in_text(text: &str, occurrences: &[ReplaceOccurrence], replace_text: &str) -> (String, usize) {
    let mut lines: Vec<String> = text
        .split_inclusive('\n')
        .map(ToString::to_string)
        .collect();
    if lines.is_empty() {
        lines.push(String::new());
    }

    let mut by_line: HashMap<usize, Vec<ReplaceOccurrence>> = HashMap::new();
    for occurrence in occurrences {
        by_line.entry(occurrence.line_number).or_default().push(occurrence.clone());
    }

    let mut replaced_count = 0;
    for (line_number, mut line_occurrences) in by_line {
        if line_number == 0 || line_number > lines.len() {
            continue;
        }
        let line = &lines[line_number - 1];
        let (body, ending) = split_line_ending(line);
        let mut body = body.to_string();
        line_occurrences.sort_by(|left, right| right.pos.cmp(&left.pos));
        for occurrence in line_occurrences {
            if let Some((start, end)) = char_range_to_byte_range(&body, occurrence.pos, occurrence.length) {
                body.replace_range(start..end, replace_text);
                replaced_count += 1;
            }
        }
        lines[line_number - 1] = format!("{body}{ending}");
    }

    (lines.concat(), replaced_count)
}

fn split_line_ending(line: &str) -> (&str, &str) {
    if let Some(body) = line.strip_suffix("\r\n") {
        (body, "\r\n")
    } else if let Some(body) = line.strip_suffix('\n') {
        (body, "\n")
    } else if let Some(body) = line.strip_suffix('\r') {
        (body, "\r")
    } else {
        (line, "")
    }
}

fn char_range_to_byte_range(text: &str, pos: usize, length: usize) -> Option<(usize, usize)> {
    let start = char_index_to_byte_index(text, pos)?;
    let end = char_index_to_byte_index(text, pos + length)?;
    Some((start, end))
}

fn char_index_to_byte_index(text: &str, char_index: usize) -> Option<usize> {
    if char_index == text.chars().count() {
        return Some(text.len());
    }
    text.char_indices().nth(char_index).map(|(byte_index, _)| byte_index)
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
    
    match pdx_inspector::detect_file_type(&raw) {
        pdx_inspector::FileType::Binary => {
            Err(io::Error::new(io::ErrorKind::InvalidData, "binary file"))
        }
        pdx_inspector::FileType::Text(enc) => {
            match enc {
                pdx_inspector::EncodingType::Utf8Bom => {
                    let (text, _, _) = UTF_8.decode(&raw[3..]);
                    Ok((text.into_owned(), "utf-8-sig".to_string()))
                }
                pdx_inspector::EncodingType::Utf16Le => {
                    let (text, _, _) = UTF_16LE.decode(&raw[2..]);
                    Ok((text.into_owned(), "utf-16-le".to_string()))
                }
                pdx_inspector::EncodingType::Utf16Be => {
                    let (text, _, _) = UTF_16BE.decode(&raw[2..]);
                    Ok((text.into_owned(), "utf-16-be".to_string()))
                }
                pdx_inspector::EncodingType::Utf8 => {
                    let (text, _, _) = UTF_8.decode(&raw);
                    Ok((text.into_owned(), "utf-8".to_string()))
                }
                pdx_inspector::EncodingType::Cp932 => {
                    let (text, _, _) = SHIFT_JIS.decode(&raw);
                    Ok((text.into_owned(), "cp932".to_string()))
                }
                pdx_inspector::EncodingType::Unknown => {
                    let (text, _, had_errors) = UTF_8.decode(&raw);
                    if !had_errors {
                        Ok((text.into_owned(), "utf-8".to_string()))
                    } else {
                        let (text, _, _) = SHIFT_JIS.decode(&raw);
                        Ok((text.into_owned(), "cp932".to_string()))
                    }
                }
            }
        }
    }
}

fn write_text_file(path: &Path, text: &str, encoding: &str) -> io::Result<()> {
    let bytes = match encoding.to_ascii_lowercase().as_str() {
        "utf-8-sig" => {
            let mut bytes = vec![0xef, 0xbb, 0xbf];
            bytes.extend_from_slice(text.as_bytes());
            bytes
        }
        "utf-16-le" => {
            let mut bytes = vec![0xff, 0xfe];
            for code_unit in text.encode_utf16() {
                bytes.extend_from_slice(&code_unit.to_le_bytes());
            }
            bytes
        }
        "utf-16-be" => {
            let mut bytes = vec![0xfe, 0xff];
            for code_unit in text.encode_utf16() {
                bytes.extend_from_slice(&code_unit.to_be_bytes());
            }
            bytes
        }
        "cp932" | "shift_jis" | "shift-jis" => {
            let (encoded, _, _) = SHIFT_JIS.encode(text);
            encoded.into_owned()
        }
        _ => text.as_bytes().to_vec(),
    };
    fs::write(path, bytes)
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
