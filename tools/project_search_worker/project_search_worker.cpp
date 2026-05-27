#include <algorithm>
#include <cctype>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <regex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#endif

namespace fs = std::filesystem;

struct JsonValue {
    enum class Type { Null, Bool, Number, String, Array, Object };
    Type type = Type::Null;
    bool boolean = false;
    double number = 0;
    std::string text;
    std::vector<JsonValue> array;
    std::map<std::string, JsonValue> object;
};

class JsonParser {
public:
    explicit JsonParser(std::string source) : source_(std::move(source)) {}

    static void append_utf8(std::string& out, uint32_t codepoint) {
        if (codepoint <= 0x7f) {
            out.push_back(static_cast<char>(codepoint));
        } else if (codepoint <= 0x7ff) {
            out.push_back(static_cast<char>(0xc0 | (codepoint >> 6)));
            out.push_back(static_cast<char>(0x80 | (codepoint & 0x3f)));
        } else if (codepoint <= 0xffff) {
            out.push_back(static_cast<char>(0xe0 | (codepoint >> 12)));
            out.push_back(static_cast<char>(0x80 | ((codepoint >> 6) & 0x3f)));
            out.push_back(static_cast<char>(0x80 | (codepoint & 0x3f)));
        } else {
            out.push_back(static_cast<char>(0xf0 | (codepoint >> 18)));
            out.push_back(static_cast<char>(0x80 | ((codepoint >> 12) & 0x3f)));
            out.push_back(static_cast<char>(0x80 | ((codepoint >> 6) & 0x3f)));
            out.push_back(static_cast<char>(0x80 | (codepoint & 0x3f)));
        }
    }

    JsonValue parse() {
        skip_ws();
        JsonValue value = parse_value();
        skip_ws();
        if (pos_ != source_.size()) {
            throw std::runtime_error("invalid json: trailing data");
        }
        return value;
    }

private:
    std::string source_;
    size_t pos_ = 0;

    void skip_ws() {
        while (pos_ < source_.size() && std::isspace(static_cast<unsigned char>(source_[pos_]))) {
            ++pos_;
        }
    }

    char peek() const {
        if (pos_ >= source_.size()) {
            throw std::runtime_error("invalid json: unexpected end");
        }
        return source_[pos_];
    }

    char get() {
        char ch = peek();
        ++pos_;
        return ch;
    }

    void expect(char expected) {
        if (get() != expected) {
            throw std::runtime_error("invalid json: unexpected character");
        }
    }

    bool consume(std::string_view literal) {
        if (source_.compare(pos_, literal.size(), literal) != 0) {
            return false;
        }
        pos_ += literal.size();
        return true;
    }

    JsonValue parse_value() {
        skip_ws();
        char ch = peek();
        if (ch == '"') {
            JsonValue value;
            value.type = JsonValue::Type::String;
            value.text = parse_string();
            return value;
        }
        if (ch == '{') {
            return parse_object();
        }
        if (ch == '[') {
            return parse_array();
        }
        if (ch == 't' && consume("true")) {
            JsonValue value;
            value.type = JsonValue::Type::Bool;
            value.boolean = true;
            return value;
        }
        if (ch == 'f' && consume("false")) {
            JsonValue value;
            value.type = JsonValue::Type::Bool;
            value.boolean = false;
            return value;
        }
        if (ch == 'n' && consume("null")) {
            return {};
        }
        if (ch == '-' || std::isdigit(static_cast<unsigned char>(ch))) {
            return parse_number();
        }
        throw std::runtime_error("invalid json: invalid value");
    }

    JsonValue parse_object() {
        JsonValue value;
        value.type = JsonValue::Type::Object;
        expect('{');
        skip_ws();
        if (peek() == '}') {
            ++pos_;
            return value;
        }
        while (true) {
            skip_ws();
            std::string key = parse_string();
            skip_ws();
            expect(':');
            value.object.emplace(std::move(key), parse_value());
            skip_ws();
            char ch = get();
            if (ch == '}') {
                break;
            }
            if (ch != ',') {
                throw std::runtime_error("invalid json: expected comma");
            }
        }
        return value;
    }

    JsonValue parse_array() {
        JsonValue value;
        value.type = JsonValue::Type::Array;
        expect('[');
        skip_ws();
        if (peek() == ']') {
            ++pos_;
            return value;
        }
        while (true) {
            value.array.push_back(parse_value());
            skip_ws();
            char ch = get();
            if (ch == ']') {
                break;
            }
            if (ch != ',') {
                throw std::runtime_error("invalid json: expected comma");
            }
        }
        return value;
    }

    JsonValue parse_number() {
        size_t start = pos_;
        if (source_[pos_] == '-') {
            ++pos_;
        }
        while (pos_ < source_.size() && std::isdigit(static_cast<unsigned char>(source_[pos_]))) {
            ++pos_;
        }
        if (pos_ < source_.size() && source_[pos_] == '.') {
            ++pos_;
            while (pos_ < source_.size() && std::isdigit(static_cast<unsigned char>(source_[pos_]))) {
                ++pos_;
            }
        }
        JsonValue value;
        value.type = JsonValue::Type::Number;
        value.number = std::stod(source_.substr(start, pos_ - start));
        return value;
    }

    std::string parse_string() {
        expect('"');
        std::string out;
        while (true) {
            char ch = get();
            if (ch == '"') {
                break;
            }
            if (ch != '\\') {
                out.push_back(ch);
                continue;
            }

            char escaped = get();
            switch (escaped) {
            case '"': out.push_back('"'); break;
            case '\\': out.push_back('\\'); break;
            case '/': out.push_back('/'); break;
            case 'b': out.push_back('\b'); break;
            case 'f': out.push_back('\f'); break;
            case 'n': out.push_back('\n'); break;
            case 'r': out.push_back('\r'); break;
            case 't': out.push_back('\t'); break;
            case 'u': {
                uint32_t codepoint = parse_hex4();
                if (codepoint >= 0xd800 && codepoint <= 0xdbff) {
                    if (get() != '\\' || get() != 'u') {
                        throw std::runtime_error("invalid json: broken surrogate pair");
                    }
                    uint32_t low = parse_hex4();
                    codepoint = 0x10000 + ((codepoint - 0xd800) << 10) + (low - 0xdc00);
                }
                append_utf8(out, codepoint);
                break;
            }
            default:
                throw std::runtime_error("invalid json: invalid escape");
            }
        }
        return out;
    }

    uint32_t parse_hex4() {
        uint32_t value = 0;
        for (int i = 0; i < 4; ++i) {
            char ch = get();
            value <<= 4;
            if (ch >= '0' && ch <= '9') value += ch - '0';
            else if (ch >= 'a' && ch <= 'f') value += ch - 'a' + 10;
            else if (ch >= 'A' && ch <= 'F') value += ch - 'A' + 10;
            else throw std::runtime_error("invalid json: invalid unicode escape");
        }
        return value;
    }
};

const JsonValue& field(const JsonValue& object, const std::string& key) {
    auto it = object.object.find(key);
    if (it == object.object.end()) {
        static JsonValue null_value;
        return null_value;
    }
    return it->second;
}

std::string as_string(const JsonValue& value, const std::string& fallback = {}) {
    return value.type == JsonValue::Type::String ? value.text : fallback;
}

bool as_bool(const JsonValue& value, bool fallback = false) {
    return value.type == JsonValue::Type::Bool ? value.boolean : fallback;
}

int as_int(const JsonValue& value, int fallback = 0) {
    return value.type == JsonValue::Type::Number ? static_cast<int>(value.number) : fallback;
}

std::vector<std::string> as_string_array(const JsonValue& value) {
    std::vector<std::string> out;
    if (value.type != JsonValue::Type::Array) {
        return out;
    }
    for (const auto& item : value.array) {
        if (item.type == JsonValue::Type::String) {
            out.push_back(item.text);
        }
    }
    return out;
}

std::string read_all_bytes(const fs::path& path, size_t limit = 0) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        throw std::runtime_error("cannot open file");
    }
    std::ostringstream buffer;
    if (limit == 0) {
        buffer << input.rdbuf();
    } else {
        std::vector<char> chunk(limit);
        input.read(chunk.data(), static_cast<std::streamsize>(chunk.size()));
        buffer.write(chunk.data(), input.gcount());
    }
    return buffer.str();
}

std::string json_escape(const std::string& value) {
    std::string out;
    out.reserve(value.size() + 16);
    for (unsigned char ch : value) {
        switch (ch) {
        case '"': out += "\\\""; break;
        case '\\': out += "\\\\"; break;
        case '\b': out += "\\b"; break;
        case '\f': out += "\\f"; break;
        case '\n': out += "\\n"; break;
        case '\r': out += "\\r"; break;
        case '\t': out += "\\t"; break;
        default:
            if (ch < 0x20) {
                const char* hex = "0123456789abcdef";
                out += "\\u00";
                out.push_back(hex[ch >> 4]);
                out.push_back(hex[ch & 0xf]);
            } else {
                out.push_back(static_cast<char>(ch));
            }
        }
    }
    return out;
}

#ifdef _WIN32
std::wstring utf8_to_wide(const std::string& value) {
    if (value.empty()) {
        return {};
    }
    int length = MultiByteToWideChar(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), nullptr, 0);
    std::wstring out(length, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), out.data(), length);
    return out;
}

std::string wide_to_utf8(const std::wstring& value) {
    if (value.empty()) {
        return {};
    }
    int length = WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), nullptr, 0, nullptr, nullptr);
    std::string out(length, '\0');
    WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), out.data(), length, nullptr, nullptr);
    return out;
}

std::string multibyte_to_utf8(const std::string& value, UINT codepage) {
    if (value.empty()) {
        return {};
    }
    int wide_length = MultiByteToWideChar(codepage, 0, value.data(), static_cast<int>(value.size()), nullptr, 0);
    if (wide_length <= 0) {
        return value;
    }
    std::wstring wide(wide_length, L'\0');
    MultiByteToWideChar(codepage, 0, value.data(), static_cast<int>(value.size()), wide.data(), wide_length);
    return wide_to_utf8(wide);
}
#endif

fs::path path_from_utf8(const std::string& value) {
#ifdef _WIN32
    return fs::path(utf8_to_wide(value));
#else
    return fs::path(value);
#endif
}

std::string path_to_utf8(const fs::path& path) {
#ifdef _WIN32
    return wide_to_utf8(path.wstring());
#else
    return path.string();
#endif
}

bool is_valid_utf8(const std::string& value) {
    size_t i = 0;
    while (i < value.size()) {
        unsigned char ch = static_cast<unsigned char>(value[i]);
        size_t needed = 0;
        if (ch <= 0x7f) needed = 0;
        else if ((ch & 0xe0) == 0xc0) needed = 1;
        else if ((ch & 0xf0) == 0xe0) needed = 2;
        else if ((ch & 0xf8) == 0xf0) needed = 3;
        else return false;
        if (i + needed >= value.size()) {
            return false;
        }
        for (size_t j = 1; j <= needed; ++j) {
            if ((static_cast<unsigned char>(value[i + j]) & 0xc0) != 0x80) {
                return false;
            }
        }
        i += needed + 1;
    }
    return true;
}

std::string utf16_to_utf8(const std::string& raw, bool little_endian) {
    std::wstring wide;
    for (size_t i = 2; i + 1 < raw.size(); i += 2) {
        uint16_t code = little_endian
            ? static_cast<uint8_t>(raw[i]) | (static_cast<uint8_t>(raw[i + 1]) << 8)
            : (static_cast<uint8_t>(raw[i]) << 8) | static_cast<uint8_t>(raw[i + 1]);
        wide.push_back(static_cast<wchar_t>(code));
    }
#ifdef _WIN32
    return wide_to_utf8(wide);
#else
    std::string out;
    for (wchar_t ch : wide) {
        JsonParser::append_utf8(out, static_cast<uint32_t>(ch));
    }
    return out;
#endif
}

struct TextFile {
    std::string text;
    std::string encoding;
    bool valid = false;
};

TextFile decode_text_file(const fs::path& path) {
    std::string raw = read_all_bytes(path, 1024 * 1024 * 5);
    if (raw.find('\0') != std::string::npos && !(raw.size() >= 2 && (static_cast<unsigned char>(raw[0]) == 0xff || static_cast<unsigned char>(raw[0]) == 0xfe))) {
        return {};
    }
    if (raw.size() >= 3 && static_cast<unsigned char>(raw[0]) == 0xef && static_cast<unsigned char>(raw[1]) == 0xbb && static_cast<unsigned char>(raw[2]) == 0xbf) {
        return { raw.substr(3), "utf-8-sig", true };
    }
    if (raw.size() >= 2 && static_cast<unsigned char>(raw[0]) == 0xff && static_cast<unsigned char>(raw[1]) == 0xfe) {
        return { utf16_to_utf8(raw, true), "utf-16-le", true };
    }
    if (raw.size() >= 2 && static_cast<unsigned char>(raw[0]) == 0xfe && static_cast<unsigned char>(raw[1]) == 0xff) {
        return { utf16_to_utf8(raw, false), "utf-16-be", true };
    }
    if (is_valid_utf8(raw)) {
        return { raw, "utf-8", true };
    }
#ifdef _WIN32
    return { multibyte_to_utf8(raw, 932), "cp932", true };
#else
    return { raw, "utf-8", true };
#endif
}

std::string lower_ascii(std::string value) {
    for (char& ch : value) {
        ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
    }
    return value;
}

bool glob_match_impl(const std::string& pattern, size_t p, const std::string& text, size_t t) {
    while (p < pattern.size()) {
        if (pattern[p] == '*') {
            while (p + 1 < pattern.size() && pattern[p + 1] == '*') {
                ++p;
            }
            if (p + 1 == pattern.size()) {
                return true;
            }
            for (size_t i = t; i <= text.size(); ++i) {
                if (glob_match_impl(pattern, p + 1, text, i)) {
                    return true;
                }
            }
            return false;
        }
        if (t >= text.size()) {
            return false;
        }
        if (pattern[p] != '?' && pattern[p] != text[t]) {
            return false;
        }
        ++p;
        ++t;
    }
    return t == text.size();
}

bool glob_match(const std::string& name, const std::vector<std::string>& patterns) {
    std::string lowered_name = lower_ascii(name);
    for (const std::string& pattern : patterns) {
        if (glob_match_impl(lower_ascii(pattern), 0, lowered_name, 0)) {
            return true;
        }
    }
    return false;
}

bool is_word_byte(char ch) {
    unsigned char value = static_cast<unsigned char>(ch);
    return std::isalnum(value) || ch == '_';
}

size_t utf8_codepoint_count(const std::string& value, size_t begin, size_t end) {
    size_t count = 0;
    for (size_t i = begin; i < end && i < value.size();) {
        unsigned char ch = static_cast<unsigned char>(value[i]);
        size_t step = 1;
        if ((ch & 0xe0) == 0xc0) step = 2;
        else if ((ch & 0xf0) == 0xe0) step = 3;
        else if ((ch & 0xf8) == 0xf0) step = 4;
        i += step;
        ++count;
    }
    return count;
}

std::vector<std::string> split_lines(const std::string& text) {
    std::vector<std::string> lines;
    size_t start = 0;
    for (size_t i = 0; i < text.size(); ++i) {
        if (text[i] == '\n' || text[i] == '\r') {
            lines.push_back(text.substr(start, i - start));
            if (text[i] == '\r' && i + 1 < text.size() && text[i + 1] == '\n') {
                ++i;
            }
            start = i + 1;
        }
    }
    if (start <= text.size()) {
        lines.push_back(text.substr(start));
    }
    return lines;
}

struct Occurrence {
    int line_number = 0;
    std::string line_text;
    std::string display_text;
    std::string tooltip_text;
    int pos = 0;
    int length = 0;
    std::string encoding;
};

struct Query {
    std::string search_text;
    std::string regex_pattern;
    bool match_case = false;
    bool use_regex = false;
    bool whole_word = false;
};

std::string occurrence_key(const std::string& path, const Occurrence& occurrence) {
    return path + "\x1f" + std::to_string(occurrence.line_number) + "\x1f" +
        std::to_string(occurrence.pos) + "\x1f" + std::to_string(occurrence.length) + "\x1f" +
        occurrence.line_text;
}

std::string trim_for_display(const std::string& value) {
    size_t begin = 0;
    while (begin < value.size() && std::isspace(static_cast<unsigned char>(value[begin]))) {
        ++begin;
    }
    size_t end = value.size();
    while (end > begin && std::isspace(static_cast<unsigned char>(value[end - 1]))) {
        --end;
    }
    return value.substr(begin, end - begin);
}

Occurrence make_occurrence(int line_number, const std::string& line, size_t byte_pos, size_t byte_end, const std::string& encoding) {
    int pos = static_cast<int>(utf8_codepoint_count(line, 0, byte_pos));
    int length = static_cast<int>(utf8_codepoint_count(line, byte_pos, byte_end));
    std::string trimmed_line = trim_for_display(line);
    std::string display_text = std::to_string(line_number) + ": " + trimmed_line;
    return {
        line_number,
        line,
        display_text,
        line,
        pos,
        length,
        encoding,
    };
}

std::vector<Occurrence> search_text(const std::string& text, const std::string& encoding, const Query& query) {
    std::vector<Occurrence> occurrences;
    std::vector<std::string> lines = split_lines(text);
    if (query.use_regex) {
        std::regex::flag_type flags = std::regex::ECMAScript;
        if (!query.match_case) {
            flags |= std::regex::icase;
        }
        std::regex pattern(query.regex_pattern, flags);
        for (size_t line_index = 0; line_index < lines.size(); ++line_index) {
            const std::string& line = lines[line_index];
            for (std::sregex_iterator it(line.begin(), line.end(), pattern), end; it != end; ++it) {
                size_t byte_pos = static_cast<size_t>(it->position());
                size_t byte_len = static_cast<size_t>(it->length());
                occurrences.push_back(make_occurrence(
                    static_cast<int>(line_index + 1),
                    line,
                    byte_pos,
                    byte_pos + byte_len,
                    encoding
                ));
            }
        }
        return occurrences;
    }

    std::string needle = query.match_case ? query.search_text : lower_ascii(query.search_text);
    if (needle.empty()) {
        return occurrences;
    }
    for (size_t line_index = 0; line_index < lines.size(); ++line_index) {
        const std::string& line = lines[line_index];
        std::string haystack = query.match_case ? line : lower_ascii(line);
        size_t from = 0;
        while (true) {
            size_t byte_pos = haystack.find(needle, from);
            if (byte_pos == std::string::npos) {
                break;
            }
            size_t byte_end = byte_pos + needle.size();
            bool word_ok = true;
            if (query.whole_word) {
                bool left_word = byte_pos > 0 && is_word_byte(line[byte_pos - 1]);
                bool right_word = byte_end < line.size() && is_word_byte(line[byte_end]);
                word_ok = !left_word && !right_word;
            }
            if (word_ok) {
                occurrences.push_back(make_occurrence(
                    static_cast<int>(line_index + 1),
                    line,
                    byte_pos,
                    byte_end,
                    encoding
                ));
            }
            from = byte_end > byte_pos ? byte_end : byte_pos + 1;
        }
    }
    return occurrences;
}

struct FileResult {
    std::string path;
    std::vector<Occurrence> occurrences;
};

std::string base_name_utf8(const std::string& path) {
    return path_to_utf8(path_from_utf8(path).filename());
}

bool include_file(const std::string& path, const std::vector<std::string>& include_patterns, const std::vector<std::string>& exclude_patterns) {
    std::string name = base_name_utf8(path);
    if (glob_match(name, exclude_patterns)) {
        return false;
    }
    return include_patterns.empty() || glob_match(name, include_patterns);
}

std::string result_to_json(const std::vector<FileResult>& results) {
    size_t match_count = 0;
    for (const auto& result : results) {
        match_count += result.occurrences.size();
    }

    std::ostringstream out;
    out << "{\"files_found\":" << results.size() << ",\"matches_found\":" << match_count << ",\"files\":[";
    bool first_file = true;
    for (const auto& result : results) {
        if (!first_file) out << ',';
        first_file = false;
        out << "{\"path\":\"" << json_escape(result.path) << "\",\"occurrences\":[";
        bool first_occurrence = true;
        for (const auto& occurrence : result.occurrences) {
            if (!first_occurrence) out << ',';
            first_occurrence = false;
            out << "{\"line_number\":" << occurrence.line_number
                << ",\"line_text\":\"" << json_escape(occurrence.line_text)
                << "\",\"display_text\":\"" << json_escape(occurrence.display_text)
                << "\",\"tooltip_text\":\"" << json_escape(occurrence.tooltip_text)
                << "\",\"pos\":" << occurrence.pos
                << ",\"length\":" << occurrence.length
                << ",\"encoding\":\"" << json_escape(occurrence.encoding) << "\"}";
        }
        out << "]}";
    }
    out << "]}";
    return out.str();
}

std::vector<FileResult> run_search(const JsonValue& request) {
    std::string project_path = as_string(field(request, "project_path"));
    std::vector<std::string> include_patterns = as_string_array(field(request, "include_patterns"));
    std::vector<std::string> exclude_patterns = as_string_array(field(request, "exclude_patterns"));

    const JsonValue& query_object = field(request, "query");
    Query query;
    query.search_text = as_string(field(query_object, "search_text"));
    query.regex_pattern = as_string(field(query_object, "regex_pattern"));
    query.match_case = as_bool(field(query_object, "match_case"));
    query.use_regex = as_bool(field(query_object, "use_regex"));
    query.whole_word = as_bool(field(query_object, "whole_word"));

    std::unordered_map<std::string, std::string> open_editors;
    const JsonValue& open_editor_values = field(request, "open_editors");
    if (open_editor_values.type == JsonValue::Type::Array) {
        for (const JsonValue& editor : open_editor_values.array) {
            open_editors[as_string(field(editor, "path"))] = as_string(field(editor, "content"));
        }
    }

    std::unordered_set<std::string> ignored;
    const JsonValue& ignored_values = field(request, "ignored_occurrences");
    if (ignored_values.type == JsonValue::Type::Array) {
        for (const JsonValue& item : ignored_values.array) {
            Occurrence occurrence;
            occurrence.line_number = as_int(field(item, "line_number"));
            occurrence.pos = as_int(field(item, "pos"));
            occurrence.length = as_int(field(item, "length"));
            occurrence.line_text = as_string(field(item, "line_text"));
            ignored.insert(occurrence_key(as_string(field(item, "path")), occurrence));
        }
    }

    std::set<std::string> target_files;
    if (!project_path.empty()) {
        fs::path root = path_from_utf8(project_path);
        fs::directory_options options = fs::directory_options::skip_permission_denied;
        for (fs::recursive_directory_iterator it(root, options), end; it != end; ++it) {
            std::error_code ec;
            std::string name = path_to_utf8(it->path().filename());
            if (it->is_directory(ec)) {
                if (glob_match(name, exclude_patterns)) {
                    it.disable_recursion_pending();
                }
                continue;
            }
            if (!it->is_regular_file(ec)) {
                continue;
            }
            std::string path = path_to_utf8(it->path());
            if (include_file(path, include_patterns, exclude_patterns)) {
                target_files.insert(path);
            }
        }
    }
    for (const auto& [path, content] : open_editors) {
        if (include_file(path, include_patterns, exclude_patterns)) {
            target_files.insert(path);
        }
    }

    std::vector<FileResult> results;
    for (const std::string& path : target_files) {
        std::string text;
        std::string encoding = "utf-8";
        auto open_it = open_editors.find(path);
        if (open_it != open_editors.end()) {
            text = open_it->second;
        } else {
            try {
                TextFile file = decode_text_file(path_from_utf8(path));
                if (!file.valid) {
                    continue;
                }
                text = std::move(file.text);
                encoding = std::move(file.encoding);
            } catch (...) {
                continue;
            }
        }

        std::vector<Occurrence> occurrences = search_text(text, encoding, query);
        occurrences.erase(
            std::remove_if(occurrences.begin(), occurrences.end(), [&](const Occurrence& occurrence) {
                return ignored.find(occurrence_key(path, occurrence)) != ignored.end();
            }),
            occurrences.end()
        );
        if (!occurrences.empty()) {
            results.push_back({ path, std::move(occurrences) });
        }
    }
    return results;
}

int main(int argc, char** argv) {
    try {
        if (argc != 5 || std::string(argv[1]) != "--request" || std::string(argv[3]) != "--response") {
            std::cerr << "usage: project_search_worker --request <request.json> --response <response.json>\n";
            return 2;
        }
        std::string request_json = read_all_bytes(path_from_utf8(argv[2]));
        JsonValue request = JsonParser(std::move(request_json)).parse();
        std::ofstream output(path_from_utf8(argv[4]), std::ios::binary);
        if (!output) {
            throw std::runtime_error("cannot open response file");
        }
        output << result_to_json(run_search(request));
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
