# MoneyPrinterTurbo 💸

MoneyPrinterTurboは、ビデオのトピックまたはキーワードを提供するだけで、自動的にビデオコピー、ビデオ素材、ビデオ字幕、ビデオ背景音楽を生成し、高解像度のショートビデオを合成します。

## 特別な感謝 🙏

このプロジェクトの**デプロイメント**と**使用**には、初心者ユーザーにとってある程度の閾値があります。そのため、このプロジェクトに基づいて無料の`AIビデオジェネレーター`サービスを提供している**RecCloud（AIパワードマルチメディアサービスプラットフォーム）**に特別な感謝を表します。これにより、デプロイメントなしでオンラインで使用でき、非常に便利です。

https://reccloud.com

## 機能 🎯

- [x] 完全な**MVCアーキテクチャ**、**明確な構造**のコード、メンテナンスが容易で、`API`と`Webインターフェース`の両方をサポート
- [x] **AI生成**ビデオコピーのサポート、および**カスタマイズされたコピー**
- [x] 様々な**高解像度ビデオ**サイズのサポート
    - [x] ポートレート9:16、`1080x1920`
    - [x] ランドスケープ16:9、`1920x1080`
- [x] **バッチビデオ生成**のサポート、一度に複数のビデオを作成し、最も満足のいくものを選択
- [x] ビデオクリップの**期間設定**のサポート、素材の切り替え頻度を調整しやすい
- [x] **中国語**と**英語**のビデオコピーのサポート
- [x] **複数の声**合成のサポート
- [x] **字幕生成**のサポート、`フォント`、`位置`、`色`、`サイズ`の調整が可能で、`字幕のアウトライン`もサポート
- [x] **背景音楽**のサポート、ランダムまたは指定された音楽ファイル、`背景音楽の音量`の調整が可能
- [x] ビデオ素材のソースは**高解像度**で**ロイヤリティフリー**
- [x] **OpenAI**、**moonshot**、**Azure**、**gpt4free**、**one-api**、**千問**、**Google Gemini**、**Ollama**など、様々なモデルとの統合をサポート

### 今後の計画 📅

- [ ] GPT-SoVITSのダビングサポートの導入
- [ ] 大型モデルを使用した音声合成の強化、より自然で感情豊かな音声出力を実現
- [ ] ビデオトランジションエフェクトの導入、よりスムーズな視聴体験を提供
- [ ] ビデオコンテンツの関連性の向上
- [ ] ビデオの長さのオプションの追加：短い、中程度、長い
- [ ] WindowsおよびmacOS用のアプリケーションをワンクリックで起動するバンドルにパッケージ化し、使用を容易にする
- [ ] カスタム素材の使用を可能にする
- [ ] ボイスオーバーと背景音楽のオプションをリアルタイムプレビューで提供
- [ ] OpenAI TTS、Azure TTSなど、より多くの音声合成プロバイダーのサポート
- [ ] YouTubeプラットフォームへのアップロードプロセスの自動化

## インストールとデプロイメント 📥

- **中国語のパス**の使用を避けることで、予測不可能な問題を防ぐ
- **ネットワーク**が安定していることを確認すること、つまり、海外のウェブサイトに正常にアクセスできること

#### ① プロジェクトのクローン

```shell
git clone https://github.com/harry0703/MoneyPrinterTurbo.git
```

#### ② 設定ファイルの変更

- `config.example.toml`ファイルをコピーして`config.toml`という名前に変更する
- `config.toml`ファイルの指示に従って、`pexels_api_keys`と`llm_provider`を設定し、llm_providerのサービスプロバイダーに応じて、対応するAPIキーを設定する

#### ③ 大言語モデル（LLM）の設定

- `GPT-4.0`または`GPT-3.5`を使用するには、`OpenAI`の`APIキー`が必要です。持っていない場合は、`llm_provider`を`g4f`に設定することができます（無料で使用できるGPTライブラリ https://github.com/xtekky/gpt4free ですが、この無料サービスの安定性は低く、時には使用できることもあれば、使用できないこともあります）。

### Dockerデプロイメント 🐳

#### ① Dockerコンテナの起動

Dockerがインストールされていない場合は、まずインストールしてください https://www.docker.com/products/docker-desktop/
Windowsシステムを使用している場合は、Microsoftのドキュメントを参照してください：

1. https://learn.microsoft.com/ja-jp/windows/wsl/install
2. https://learn.microsoft.com/ja-jp/windows/wsl/tutorials/wsl-containers

```shell
cd MoneyPrinterTurbo
docker-compose up
```

#### ② Webインターフェースにアクセス

ブラウザを開いて http://0.0.0.0:8501 にアクセス

#### ③ APIインターフェースにアクセス

ブラウザを開いて http://0.0.0.0:8080/docs または http://0.0.0.0:8080/redoc にアクセス

### 手動デプロイメント 📦

#### ① Python仮想環境の作成

[conda](https://conda.io/projects/conda/en/latest/user-guide/install/index.html)を使用してPython仮想環境を作成することをお勧めします

```shell
git clone https://github.com/harry0703/MoneyPrinterTurbo.git
cd MoneyPrinterTurbo
conda create -n MoneyPrinterTurbo python=3.10
conda activate MoneyPrinterTurbo
pip install -r requirements.txt
```

#### ② ImageMagickのインストール

###### Windows:

- https://imagemagick.org/archive/binaries/ImageMagick-7.1.1-30-Q16-x64-static.exe をダウンロード
- ダウンロードしたImageMagickをインストール、インストールパスを変更しないでください
- `config.toml`設定ファイルを変更し、`imagemagick_path`を実際のインストールパスに設定します（インストール時にパスを変更していない場合は、コメントを外すだけで大丈夫です）

###### MacOS:

```shell
brew install imagemagick
```

###### Ubuntu

```shell
sudo apt-get install imagemagick
```

###### CentOS

```shell
sudo yum install ImageMagick
```

#### ③ Webインターフェースの起動 🌐

MoneyPrinterTurboプロジェクトの`ルートディレクトリ`で以下のコマンドを実行してください

###### Windows

```bat
conda activate MoneyPrinterTurbo
webui.bat
```

###### MacOSまたはLinux

```shell
conda activate MoneyPrinterTurbo
sh webui.sh
```

起動後、ブラウザが自動的に開きます

#### ④ APIサービスの起動 🚀

```shell
python main.py
```

起動後、`APIドキュメント`を http://127.0.0.1:8080/docs または http://127.0.0.1:8080/redoc で確認し、オンラインで直接インターフェースをテストして、迅速に体験できます。
