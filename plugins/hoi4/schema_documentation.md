# 汎用スキーマ評価エンジン (Schema Evaluator) ドキュメント

このドキュメントでは、専用パーサーを代替する「汎用スキーマ評価エンジン」と、各要素（ディシジョンやイベントなど）を定義するためのJSONスキーマの記述方法について解説します。

---

## 1. 概要
`script_parser.py` 内に実装された `SchemaEvaluator` は、AST（抽象構文木）とJSONスキーマ定義を照らし合わせ、柔軟にデータを抽出・構造化するエンジンです。
各モッディング要素に合わせて `xxx_schema.json` を作成するだけで、パーサーのプログラムを直接修正することなく新しい要素に対応できます。

---

## 2. スキーマの基本構造

JSONスキーマは以下の基本プロパティを持ちます。

```json
{
  "schema_name": "hoi4_event",
  "file_scope": "events",
  "root_pattern": "named_block",
  "id_rule": { ... },
  "unknown_keys": "warn",
  "fields": { ... },
  "sub_schemas": { ... }
}
```

### 2.1. `root_pattern`
構文木のどの階層からデータを抽出するかを指定します。

- **`named_block`**
  トップレベルに記述されるブロックを抽出します。
  （例：ディシジョンカテゴリ `AIO_basic_category = { ... }`）
- **`nested_named_block`**
  トップレベルブロックの中にネストされたブロックを抽出します。
  （例：通常のディシジョン `AIO_category = { AIO_decision = { ... } }`）

### 2.2. `id_rule`
要素の「ID」をどこから取得するか（抽出ルール）を定義します。

- **`source`**
  - `"outer_key"` : ブロックのキー名そのものをIDとします（例：カテゴリ）。
  - `"key"` : ネストされた内側のキー名をIDとします（例：通常のディシジョン）。
  - `"inner_property"` : ブロックの内部に定義されたプロパティの値をIDとします。この場合、`"property_name"` でキー名（例：`"id"`）を指定する必要があります（例：イベント）。
- **`parent`**
  ネスト構造の場合に「親要素のID」をどう取得するかを定義します。ディシジョンの場合はここに `{"source": "outer_key"}` を指定し、カテゴリIDを親IDとして紐づけます。

---

## 3. フィールドと型の定義 (`fields` / `sub_schemas`)

`fields` 内では、そのブロックが持つプロパティの名前とその属性を定義します。

### 代表的なプロパティ属性
- `type`: データの型。以下の組み込み型やブロック型を指定します。
  - 基本型：`identifier`, `string`, `integer`, `boolean`
  - 参照型：`localisation_key`, `sprite_id`
  - 特殊ブロック：`trigger_block`, `effect_block`, `mtth_block`, `modifier_block`
  - 複合型：`["integer", "scripted_value_block"]` のように配列で複数指定可能。
- `required`: 必須プロパティかどうか (`true` / `false`)。
- `multiple`: 複数回の記述を許可するか (`true` / `false`)。
- `allowed_values`: 許可される値の配列（例：`["yes", "no"]`）。
- `context`: このブロックが評価されるコンテキスト（スコープ）。例：`country`, `state`。

### ネストされたオブジェクト (`sub_schemas`)
`highlight_states` やイベントの `option` のように、内部に独自のフィールドを持つ構造を定義する場合は、型を `object` にし、`sub_schemas` を利用します。

```json
  "fields": {
    "option": {
      "type": "object",
      "multiple": true,
      "schema": "event_option"  // サブスキーマを参照
    }
  },
  "sub_schemas": {
    "event_option": {
      "fields": {
        "name": { "type": "localisation_key", "required": true },
        "trigger": { "type": "trigger_block" }
      }
    }
  }
```

---

## 4. サンプル構成の比較

それぞれの用途に応じた `root_pattern` と `id_rule` の違いは以下の通りです。

### ディシジョンカテゴリ
一番外側のキーがID。
```json
  "root_pattern": "named_block",
  "id_rule": {
    "source": "outer_key",
    "role": "decision_category_id"
  }
```

### 通常のディシジョン
カテゴリにネストされ、内側のキーがID、外側が親ID。
```json
  "root_pattern": "nested_named_block",
  "id_rule": {
    "source": "key",
    "role": "decision_id",
    "parent": {
      "source": "outer_key",
      "role": "decision_category_id"
    }
  }
```

### イベント
名前付きブロックだが、IDは内部の `id = ...` から取得。
```json
  "root_pattern": "named_block",
  "id_rule": {
    "source": "inner_property",
    "property_name": "id",
    "role": "event_id"
  }
```
