# GFXエディタ実装計画書 (UI設計・2分割構成)

Hearts of Iron IV (HoI4) をはじめとする Paradox社ゲームのグラフィック定義ファイル (`.gfx`) を視覚的に編集するための GFXエディタのUI設計です。
今回の実装ではユーザーの指示に基づき、`.py` などのバックエンドロジック部分は作成せず、**設定ファイル (`config.json`)** と **Qt Designer用のUI定義ファイル (`gfx_editor.ui`)** のみを実装します。

---

## ユーザーレビューが必要な点

> [!IMPORTANT]
> 2分割UIレイアウト構成について
> ご指示に基づき、画面を横方向の `QSplitter` で **2分割（左ペインと右ペイン）** に設計します。
> - **左ペイン**: GFX定義一覧リストと操作ボタン群。
> - **右ペイン**: 上部に「詳細編集フォーム」、下部に「テクスチャプレビュー＆再生コントローラー領域」を縦に並べて配置します。
>
> これにより、定義リストを見ながら、詳細なプロパティ編集と画像プレビューを右側でまとめて確認できる、コンパクトで非常に使い勝手の良いレイアウトになります。この構成について、ご確認およびご承認をお願いします。

---

## 提案する変更内容

変更はすべて `plugins/hoi4/interface` ディレクトリ内に配置し、既存のプラグイン動的ロード機能 (`main.py` の `load_plugin_elements`) によって自動的に GFXエディタとして検出されるように設定します。

### GFXエディタコンポーネント

#### [NEW] [config.json](file:///c:/localfile/開発/pdx-mod-Studio/plugins/hoi4/interface/config.json)
GFXエディタのメタデータを定義する設定ファイルです。`.gfx` 拡張子へのマッピングと UI ファイルとの紐付けを設定します。

#### [NEW] [gfx_editor.ui](file:///c:/localfile/開発/pdx-mod-Studio/plugins/hoi4/interface/gfx_editor.ui)
Qt Designer 形式の UI 定義ファイルです。2分割レイアウトで構成された洗練されたデザインを設計します。

---

## 画面構成・UI詳細設計 (2分割版)

### 1. 全体構造 (Hoi4GfxEditor)
- `QWidget` をベースとし、トップレベルレイアウトに `QVBoxLayout` (`rootLayout`) を適用します。
- その中に `QSplitter` (`mainSplitter`, 横方向分割) を配置し、2つのパネルに分割します。

### 2. 左ペイン：GFX定義一覧 (`leftPanel` / QWidget)
- **上部タイトル**: `QLabel`「GFX定義一覧」
- **操作ボタン群 (`treeButtonGrid` / QGridLayout)**:
  - `btnAddSprite`: 「spriteType追加」
  - `btnAddFrameAnimated`: 「frameAnimated追加」
  - `btnAddProgressBar`: 「progressbar追加」
  - `btnAddCorneredTile`: 「corneredTile追加」
  - `btnAddMaskedShield`: 「maskedShield追加」
  - `btnDuplicateItem`: 「複製」
  - `btnDeleteItem`: 「削除」
- **リスト表示**: `QTreeWidget` (`treeGfxItems`) で、定義されているGFX項目を一覧表示します。

### 3. 右ペイン：編集＆プレビュー (`rightPanel` / QWidget)
右ペインは `QVBoxLayout` (`rightLayout`) を持ち、上部に編集フォーム、下部にプレビューを縦に配置します。

#### 3-1. 上部：詳細編集フォーム (`editorContainer` / QWidget)
- **上部タイトル**: `QLabel`「詳細編集」
- **エディタスタック**: `QStackedWidget` (`stackedEditor`) を配置し、左ペインで選択された項目のタイプに応じて編集ページを動的に切り替えます。
  - **ページ 1: `pageSpriteType`** (基本画像/アニメーション)
    - `editSpriteName` (QLineEdit): 定義名 (`name`)
    - `editSpriteTexture` (QLineEdit + 参照ボタン `btnSelectSpriteTexture`): 画像パス (`texturefile`)
    - `spinSpriteFrames` (QSpinBox): フレーム数 (`noOfFrames`)
    - `editSpriteEffect` (QLineEdit + 参照ボタン `btnSelectSpriteEffect`): エフェクト (`effectFile`)
    - `checkSpriteTransparent` (QCheckBox): 透過フラグ (`allwaystransparent`)
    - `checkSpriteLazyLoad` (QCheckBox): 遅延読み込み (`legacy_lazy_load`)
    - `checkSpriteTransparenceCheck` (QCheckBox): 透過度チェック (`transparencecheck`)
    - **アニメーション設定グループ (`groupSpriteAnimation` / QGroupBox)**:
      - 各種アニメーション制御用パラメータ (マスクファイル、テクスチャ、回転、ループ、時間、遅延、ブレンドモード、タイプ、オフセット、スケール、対象フレーム等) の入力用コントロール。
  - **ページ 2: `pageFrameAnimated`** (フレームアニメ)
    - パラメータ (`name`, `texturefile`, `noOfFrames`, `effectFile`, `animation_rate_fps`, `looping`, `play_on_show`, `pause_on_loop`, `allwaystransparent`) の入力欄。
  - **ページ 3: `pageProgressBar`** (プログレスバー)
    - パラメータ (`name`, `textureFile1`, `textureFile2`, `color`, `colortwo`, `size`, `effectFile`, `horizontal`, `steps`) の入力欄。
  - **ページ 4: `pageCorneredTile`** (9スライスパネル)
    - パラメータ (`name`, `texturefile`, `noOfFrames`, `size`, `borderSize`, `effectFile`, `allwaystransparent`, `tilingCenter`) の入力欄。
  - **ページ 5: `pageMaskedShield`** (国旗マスク)
    - パラメータ (`name`, `textureFile1`, `textureFile2`, `effectFile`) の入力欄。

#### 3-2. 下部：テクスチャプレビュー領域 (`previewGroupBox` / QGroupBox)
- **プレビュー画像表示**: `QScrollArea` (`scrollPreview`) の中に `QLabel` (`labelImagePreview`) を配置。
- **再生コントローラー群**:
  - `btnPlayPreview` (QToolButton): 再生/停止
  - `sliderPreviewFrame` (QSlider): 表示フレームの切り替え用スライダー
  - `labelFrameIndicator` (QLabel): 「Frame: 1 / 1」等の現在のフレーム状態表示

---

## 検証プラン

### 手動確認
1. **メタデータロード検証**:
   - プラグイン一覧から「Hearts of Iron IV」が正しく読み込まれること。
   - `test_mod/interface` フォルダにある `.gfx` ファイルがGFXエディタとして検出されるためのマッピング設定を確認。
2. **Qt Designerでのレイアウト検証**:
   - 生成した `gfx_editor.ui` を Qt Designer で開き、左右の2分割および右側の上下構成が崩れていないこと、ウィジェットの命名規則が正しいことを確認します。
