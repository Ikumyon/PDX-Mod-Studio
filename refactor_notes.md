# Note v2

## 良くなった点

`ProjectIOManager` にプロジェクト保存・読み込み処理が移動できています。`save_reference_project()`、`save_embedded_project()`、`open_reference_project()` などが `project_io.py` にまとまっているので、`main.py` の責務が軽くなっています。

`EditorTabProxy` も `editor_tabs.py` に分離されています。タブ分割、ペイン追加、タブ削除などがまとまっていて、この分離はかなり正しいです。

文字コード判定も `encoding_controller.py` に移動し、Rust 側の `pdx_inspector` を呼び出す形になっています。
さらに `inspector.py` では、5MB超をバイナリ扱いにする安全策と、Rust 側の `inspect_file()` 呼び出しが入っています。

検索処理も `SearchController` に移動できています。検索ポップアップ、Ctrl+F、検索キャッシュ、次/前検索、置換が `main.py` から外れたのは良いです。

## まだ直した方がいい点

### 1. `main.py` 内で `create_editor_tab_bar()` を再定義している

上でこれを import しています。

```python
from core.editor_tabs import EditorTabProxy, create_editor_tab_bar
```

でも `main()` の中でまた同じ名前の関数を定義しています。

```python
def create_editor_tab_bar(parent):
    tab_bar = QTabBar(parent)
    ...
```

これは `editor_tabs.py` に分離した意味が少し薄くなります。
`main.py` 側のローカル定義は削除して、import したものを使う方がよいです。

修正：

```python
# main.py 内の def create_editor_tab_bar(parent): ... を削除

editor_tab_bar = create_editor_tab_bar(tab_bar_container)
```

### 2. `ProjectIOManager` を2回 import している

ファイル冒頭ですでに import しています。

```python
from core.project_io import ProjectIOManager
```

でも後半でまたこれがあります。

```python
from core.project_io import ProjectIOManager
project_io = ProjectIOManager(...)
```

後半の import は不要です。削除してよいです。

### 3. ファイルを開く処理はまだ `main.py` に残っている

`open_file()` はまだ `main.py` 側にあります。
今の `open_file()` は以下を全部やっています。

* バイナリ判定
* 文字コード判定
* 既存タブ確認
* ファイル読み込み
* エディタ生成
* タブ追加
* エラー処理

ここも次に分離するなら、`FileOpenController` を作るのがよいです。

候補：

```text
core/
  file_open_controller.py
```

中身はこういう担当にします。

```python
class FileOpenController:
    def __init__(
        self,
        window,
        editor_tabs,
        editor_registry,
        project_tree,
        create_editor_widget,
        get_element_for_path,
        update_editor_selector,
        next_tab_id,
        text_editor_id,
    ):
        ...
```

そして `main.py` 側はこうするだけにします。

```python
file_open_controller = FileOpenController(...)

window.open_file = file_open_controller.open_file
action_open_file.triggered.connect(file_open_controller.open_file_dialog)
```

### 4. `open_file()` の例外処理がまだ `print()` のまま

今のままだと、ファイルオープン失敗時に GUI 上では分かりません。

```python
except Exception as e:
    print(f"ファイルを開けませんでした: {e}")
```

ここは `QMessageBox` か `statusBar()` がよいです。

```python
except Exception as error:
    QMessageBox.warning(
        window,
        tr("MainWindow", "ファイルオープン"),
        tr("MainWindow", "ファイルを開けませんでした: {error}").format(error=error),
    )
```

### 5. Rust 側の `utf-8-sig` の扱いは確認した方がいい

Rust 側では `"utf-8"` と `"utf-8-sig"` をどちらも `encoding_rs::UTF_8` に流しています。

```rust
"utf-8" | "utf-8-sig" => &encoding_rs::UTF_8,
```

Python の `utf-8-sig` は BOM を取り除く挙動があります。
Rust 側で BOM が本文に残るようなら、手動で BOM を除去した方がいいです。

例：

```rust
let raw = if encoding.eq_ignore_ascii_case("utf-8-sig")
    && raw.starts_with(&[0xEF, 0xBB, 0xBF])
{
    &raw[3..]
} else {
    raw
};
```

## 次にやるなら

次の整理対象は **ファイルを開く処理** です。

今の優先順位はこれです。

1. `main.py` 内の重複 `create_editor_tab_bar()` を削除
2. 重複 `ProjectIOManager` import を削除
3. `open_file()` / `open_file_dialog()` を `FileOpenController` に分離
4. `open_file()` の `print()` エラーを GUI 表示に変更
5. Rust の `utf-8-sig` BOM 処理を確認

全体としては、前回よりかなり整理されています。今の段階なら「プロジェクトIO」「タブ管理」「検索」「文字コード判定」は分離済みなので、次は `open_file()` を外に出せば `main.py` がかなり軽くなります。
