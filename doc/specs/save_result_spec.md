# 保存結果仕様

本書は、保存処理が本体へ返す結果データの公開仕様を定義する。

これは公開APIではなく、公開仕様である。

## 1. 目的

保存処理の成否、失敗、キャンセルを、本体が一貫して解釈できる形で返す。

## 2. 結果種別

- 保存成功
- 保存失敗
- 保存キャンセル

## 3. 基本構造

保存処理は、少なくとも次の形式に従う辞書を返す。

```python
{"status": "success"}
{"status": "failed"}
{"status": "cancelled"}
```

## 4. フィールド

### 必須

- `status`

`status` は次のいずれかを取る。

- `success`
- `failed`
- `cancelled`

### 任意

- `message`
- `primary_path`
- その他、本体が無視してもよい補助情報

例:

```python
{"status": "success", "primary_path": path}
{"status": "failed", "message": "write error"}
{"status": "cancelled", "message": "user cancelled"}
```

## 5. タブまたはプラグインの責務

- 保存処理全体の結果を判断する
- 本体が扱える形で結果を返す
- 必要に応じて失敗理由やキャンセル理由を保持する

## 6. 本体の責務

- 返却された結果を受け取る
- 結果に応じて後続処理へ進む
- 保存内容の詳細までは解釈しない

## 7. 判定ルール

- すべての保存対象が正常に書き込まれた場合を成功とする
- ユーザーが保存ダイアログを閉じた、または保存を取りやめた場合をキャンセルとする
- 書き込み不能や形式変換失敗などにより完了しなかった場合を失敗とする

## 8. 実装方針

この仕様は helper 関数なしでも成立しなければならない。

プラグインは本体内部 helper に依存せず、仕様どおりの辞書を直接返してよい。

## 関連文書

- プラグイン全体方針: [../plugin_model.md](../plugin_model.md)
- 公開フック: [../plugin_hooks_reference.md](../plugin_hooks_reference.md)
