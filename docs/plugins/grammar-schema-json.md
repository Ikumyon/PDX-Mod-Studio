[&larr; 戻る](./../plugin-specification.md)
# スキーマ定義ファイル (Schema JSON)

この文書は、エディタで開いた `.txt` などを汎用的に検査するための `schema` JSON の書き方を定義する。

`schema` はゲーム固有の意味を本体に埋め込まず、プラグイン側の実ファイルとして置く。本体は `syntax` でテキストを AST にし、`values` で型を判定し、`schema` の汎用語彙に従って構造を検査する。

## 基本方針

- `syntax` はコードの構文上の性格を定義する。
- `values` は型を定義する。
- `schema` は AST の構造と型の使われ方を定義する。
- 本体が知ってよいのは、`type` が型指定であること、`properties` が子要素定義であること、`usage` が出現要求であることなどの汎用語彙だけ。
- 本体はゲーム固有キー、既定 schema、既定 values を持たない。
- 必須ファイルや必須項目が無い場合は、補完せずエラーにする。
- 未定義の型名、未定義の properties 参照、壊れた JSON はエラーにする。

## ファイル配置

`schema` JSON はプラグイン配下に置く。

例:

```text
plugins/hoi4/
  plugin_manifest.json
  grammar_modes.toml
  grammar/
    syntax.toml
    values.toml
    schemas/
      decision_schema.json
      decision_category_schema.json
      properties/
        highlight_states.json
```

本体はマニフェストから辿れる定義を読み、その定義に書かれたパスの実ファイルを読む。`grammar/schemas` という場所自体を本体の固定知識にはしない。

## 最小構造

`schema` JSON は、通常 `properties` を持つ object として書く。

```json
{
  "properties": {
    "icon": {
      "type": "string",
      "usage": "optional"
    },
    "visible_when_empty": {
      "type": "boolean",
      "usage": "optional"
    }
  }
}
```

この例では、同じブロック内に `icon` と `visible_when_empty` を置ける。`string` や `boolean` の具体的な判定は `values` 側で定義する。

## Property 定義

`properties` のキーは、そのブロック内で許可する左辺名を表す。

```json
{
  "properties": {
    "priority": {
      "type": "int",
      "usage": "optional"
    }
  }
}
```

対象テキスト:

```text
priority = 10
```

`priority` の右辺 `10` が `values` の `int` 型に一致すれば valid になる。

## ワイルドカード Property

任意の左辺名を許可したい場合は `*` を使う。

```json
{
  "properties": {
    "*": {
      "usage": "required",
      "select": {
        "left": {
          "type": "id",
          "key_capture": "decision"
        },
        "right": {
          "type": {
            "is": "block",
            "properties": {
              "icon": {
                "type": "string",
                "usage": "optional"
              }
            }
          }
        }
      }
    }
  }
}
```

対象テキスト:

```text
my_decision = {
  icon = generic_decision
}
```

`*` は左辺名そのものを固定しない。左辺名の型を検査したい場合は `select.left.type` に型名を書く。

## type

`type` は右辺の型を指定する。

型名は `values` で定義された名前を使う。

### 基本の書き方

通常は以下のように、型名のみを文字列で指定する。

```json
{
  "type": "int"
}
```

### オブジェクト形式

オブジェクト形式を用いて以下のように記述することもできる。

```json
{
  "type": {
    "is": "int"
  }
}
```

どちらの書き方も全く同じ意味として扱われる。

型に追加パラメータが必要な場合は object 形式に書く。

```json
{
  "type": {
    "is": "block",
    "properties": {
      "icon": {
        "type": "string",
        "usage": "optional"
      },
      "visible_when_empty": {
        "type": "boolean",
        "usage": "optional"
      }
    }
  }
}
```

### 複数候補を許可する場合（配列）

複数の型を候補として許可する場合は、配列を使用する。
通常は以下のように記述できる。

```json
{
  "type": [
    "int",
    "variable"
  ]
}
```

これもオブジェクト形式を用いて、省略せずに以下のように記述することもできる。何かしらのパラメータを付与する場合はこちらを使用する。

```json
{
  "type": [
    {
      "is": "int"
    },
    {
      "is": "variable"
    }
  ]
}
```

この場合、どれか1つに一致すれば valid とする。

## block

`block` は `values` で定義されている通り、それ自体が型（`block`型）として扱われる。
そのため、他の型と同様に `type` にオブジェクト形式（`"is": "block"`）を指定し、パラメータとして `properties` や `items` を持つ。

右辺がブロックであることを要求する場合は、以下のように記述する。

```json
{
  "type": {
    "is": "block",
    "properties": {
      "state": {
        "type": "int",
        "usage": "optional",
        "multiple": true
      }
    }
  }
}
```

対象テキスト:

```text
highlight_state_targets = {
  state = 123
  state = 456
}
```

`properties` に object を直接書くと、その場で子要素定義を行う。

## properties 参照

共通定義を別 JSON に分ける場合、`properties` に文字列を指定する。

```json
{
  "type": {
    "is": "block",
    "properties": "highlight_states"
  }
}
```

`highlight_states` がどの実ファイルを指すかは、プラグイン側の定義で解決する。本体は名前から勝手にファイルパスを組み立てない。

参照先 JSON の例:

```json
{
  "property_id": "highlight_states",
  "properties": {
    "highlight_color_while_active": {
      "type": {
        "is": "enum",
        "allowed_values": [0, 1, 2, 3]
      },
      "usage": "optional"
    }
  }
}
```

## items

ブロック内に左辺なしの値を並べる場合は `items` を使う。

```json
{
  "type": {
    "is": "block",
    "items": {
      "type": {
        "is": "country_tag"
      }
    }
  }
}
```

対象テキスト:

```text
targets = {
  GER
  ITA
  JAP
}
```

各 item は `values` の `country_tag` 型で検査する。

## enum

schema 内に許可値を直接書きたい場合は `enum` を使う。

ただし `allowed_values` を schema 内に書く場合は、次のように object 形式を使う。

```json
{
  "type": {
    "is": "enum",
    "allowed_values": [
      "decision_view_only",
      "map_and_decisions_view",
      "map_only"
    ]
  },
  "usage": "optional"
}
```

`allowed_values` は必須。無い場合はエラーにする。

## usage

`usage` は出現要求を表す。

```json
{
  "type": "string",
  "usage": "required"
}
```

使用できる値:

- `required`: 必須
- `optional`: 任意

未指定時の扱いは schema 仕様として固定する。実装側で曖昧に補完しないため、原則として明示する。

## multiple

同じ property を複数回書ける場合は `multiple: true` を指定する。

```json
{
  "type": "int",
  "usage": "optional",
  "multiple": true
}
```

`multiple` が `true` でない property が複数回出た場合はエラーにする。

## select

assignment の左辺と右辺を別々に検査したい場合は `select` を使う。

```json
{
  "select": {
    "left": {
      "type": "id",
      "key_capture": "category"
    },
    "right": {
      "type": {
        "is": "block",
        "properties": {
          "icon": {
            "type": "string",
            "usage": "optional"
          }
        }
      }
    }
  }
}
```

`key_capture` は、後続の補完や参照検査で使うための捕捉名を表す。捕捉自体は診断の必須条件ではない。

## rules

`rules` は、単純な型や property 検査では表しにくい構造ルールを定義する。

最初に扱うルールは `exclusive` とする。

```json
{
  "rules": [
    {
      "rule": "exclusive",
      "usage": "optional",
      "match": {
        "min": 1
      },
      "severity": "warning",
      "message": "grammar.error.exclusive_cost",
      "groups": [
        ["cost"],
        ["custom_cost_trigger", "custom_cost_text"]
      ]
    }
  ]
}
```

`exclusive` は、複数 group の同時成立を検査する。`severity` が `warning` の場合は黄色波線、それ以外のエラーは赤波線にする。

`message` は翻訳キーとして扱う。未翻訳時は人間向け文言にせず、キー文字列そのものを表示する。

## severity

診断の重要度を指定する。

使用できる値:

- `error`: 赤波線
- `warning`: 黄色波線

schema に `severity` が無い通常の構文エラー、型エラー、必須欠落、未知 property は `error` とする。

## 診断位置

エディタ上の波線表示に必要なため、検査結果は行、列、長さを持つ。

schema を書く側は位置情報を直接書かない。位置は parser が AST ノードから決定する。

基本方針:

- 左辺名の問題は左辺に波線を引く。
- 右辺値の型不一致は右辺に波線を引く。
- 必須欠落は対象ブロックの開始位置、または親 property に波線を引く。
- block/value の不一致は右辺全体に波線を引く。

## よくあるエラー

型名が `values` に無い:

```json
{
  "type": {
    "is": "unknown_type"
  }
}
```

これは本体側で補完しない。`values` に型を追加するか、schema の型名を直す。

参照先 properties が定義されていない:

```json
{
  "type": {
    "is": "block",
    "properties": "triggers"
  }
}
```

`triggers` をプラグイン側の定義で解決できない場合はエラーにする。

enum に `allowed_values` が無い:

```json
{
  "type": {
    "is": "enum"
  }
}
```

これは schema 不備としてエラーにする。

## 完整な例

```json
{
  "properties": {
    "*": {
      "usage": "required",
      "select": {
        "left": {
          "type": "id",
          "key_capture": "category"
        },
        "right": {
          "type": {
            "is": "block",
            "properties": {
              "icon": {
                "type": "string",
                "usage": "optional"
              },
              "priority": {
                "type": [
                  "int",
                  {
                    "is": "block",
                    "properties": "mtth"
                  }
                ],
                "usage": "optional"
              },
              "visible_when_empty": {
                "type": "boolean",
                "usage": "optional"
              },
              "highlight_states": {
                "type": {
                  "is": "block",
                  "properties": "highlight_states"
                },
                "usage": "optional"
              }
            }
          }
        }
      }
    }
  }
}
```

この schema は、任意の category ID を左辺に持つ top-level assignment を許可し、右辺ブロック内の property を検査する。
