use encoding_rs::{SHIFT_JIS, UTF_8};
use pyo3::prelude::*;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FileType {
	Binary,
	Text(EncodingType),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EncodingType {
	Utf8,
	Utf8Bom,
	Utf16Le,
	Utf16Be,
	Cp932,
	Unknown,
}

impl EncodingType {
	pub fn as_str(&self) -> &'static str {
		match self {
			EncodingType::Utf8 => "utf-8",
			EncodingType::Utf8Bom => "utf-8-sig",
			EncodingType::Utf16Le => "utf-16-le",
			EncodingType::Utf16Be => "utf-16-be",
			EncodingType::Cp932 => "cp932",
			EncodingType::Unknown => "unknown",
		}
	}
}

/// バイトデータからファイルタイプとエンコーディングを自動検出する共通コア関数
pub fn detect_file_type(raw: &[u8]) -> FileType {
	if raw.is_empty() {
		return FileType::Text(EncodingType::Utf8);
	}

	// 1. BOM判定
	if raw.starts_with(&[0xEF, 0xBB, 0xBF]) {
		return FileType::Text(EncodingType::Utf8Bom);
	}
	if raw.starts_with(&[0xFF, 0xFE]) {
		return FileType::Text(EncodingType::Utf16Le);
	}
	if raw.starts_with(&[0xFE, 0xFF]) {
		return FileType::Text(EncodingType::Utf16Be);
	}

	// 2. バイナリ判定 (ヌルバイトチェック)
	if raw.contains(&0) {
		return FileType::Binary;
	}

	// 3. UTF-8 検証
	let (_, _, had_errors) = UTF_8.decode(raw);
	if !had_errors {
		return FileType::Text(EncodingType::Utf8);
	}

	// 4. CP932 / Shift_JIS 検証
	let (_, _, had_errors) = SHIFT_JIS.decode(raw);
	if !had_errors {
		return FileType::Text(EncodingType::Cp932);
	}

	FileType::Text(EncodingType::Unknown)
}


// =====================================================================
// 将来の PyO3 連携用 Python バインディング定義
// =====================================================================

/// Python から inspect_file(file_path) として呼び出せる関数。
/// 戻り値: (file_type_int, encoding_str)
/// - file_type_int: 1 (Binary), 2 (Text)
#[pyfunction]
pub fn inspect_file(file_path: &str) -> PyResult<(i32, String)> {
	use std::fs::File;
	use std::io::Read;
	use std::path::Path;

	let path = Path::new(file_path);
	if !path.exists() {
		return Ok((2, "unknown".to_string()));
	}

	let mut file = match File::open(path) {
		Ok(f) => f,
		Err(_) => return Ok((1, "unknown".to_string())), // 開けないファイルはバイナリ扱いとして安全に防ぐ
	};

	// 先頭 8KB のみを読み込んで高速判定
	let mut buffer = vec![0u8; 8192];
	let bytes_read = match file.read(&mut buffer) {
		Ok(n) => n,
		Err(_) => return Ok((1, "unknown".to_string())),
	};
	buffer.truncate(bytes_read);

	match detect_file_type(&buffer) {
		FileType::Binary => Ok((1, "unknown".to_string())),
		FileType::Text(enc) => Ok((2, enc.as_str().to_string())),
	}
}

/// PyO3 モジュールの初期化定義
#[pymodule]
fn pdx_inspector(m: &Bound<'_, PyModule>) -> PyResult<()> {
	m.add_function(wrap_pyfunction!(inspect_file, m)?)?;
	Ok(())
}
