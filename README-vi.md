<div align="center">
<h1 align="center">MoneyPrinterTurbo 💸</h1>

<p align="center">
  <a href="https://github.com/harry0703/MoneyPrinterTurbo/stargazers"><img src="https://img.shields.io/github/stars/harry0703/MoneyPrinterTurbo.svg?style=for-the-badge" alt="Stargazers"></a>
  <a href="https://github.com/harry0703/MoneyPrinterTurbo/issues"><img src="https://img.shields.io/github/issues/harry0703/MoneyPrinterTurbo.svg?style=for-the-badge" alt="Issues"></a>
  <a href="https://github.com/harry0703/MoneyPrinterTurbo/network/members"><img src="https://img.shields.io/github/forks/harry0703/MoneyPrinterTurbo.svg?style=for-the-badge" alt="Forks"></a>
  <a href="https://github.com/harry0703/MoneyPrinterTurbo/blob/main/LICENSE"><img src="https://img.shields.io/github/license/harry0703/MoneyPrinterTurbo.svg?style=for-the-badge" alt="License"></a>
</p>

<h3><a href="README.md">简体中文</a> | <a href="README-en.md">English</a> | <a href="README-ar.md">العربية</a> | Tiếng Việt</h3>

<div align="center">
  <a href="https://trendshift.io/repositories/8731" target="_blank"><img src="https://trendshift.io/api/badge/repositories/8731" alt="harry0703%2FMoneyPrinterTurbo | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
</div>

Chỉ cần cung cấp một <b>chủ đề</b> hoặc <b>từ khóa</b> cho video, hệ thống sẽ tự động tạo ra kịch bản video, tư liệu video, phụ đề video và nhạc nền video, sau đó tổng hợp thành một video ngắn độ nét cao.

### Giao Diện Web

![](docs/webui-en.jpg)

### Giao Diện API

![](docs/api.jpg)

</div>

## Đặc Biệt Cảm Ơn 🙏

Cảm ơn [Kimi](https://platform.kimi.ai?aff=MoneyPrinterTurbo) đã tài trợ cho dự án này! [Kimi K2.7 Code](https://platform.kimi.ai/docs/guide/kimi-k2-7-code-quickstart) là mô hình agent mã nguồn mở tập trung vào lập trình do Moonshot AI phát triển, với những cải tiến đáng kể trong các tác vụ lập trình dài hơi thực tế và tỷ lệ thành công đầu-cuối cao hơn trong các quy trình kỹ thuật phần mềm phức tạp. Nó cũng cắt giảm khoảng 30% lượng token suy nghĩ so với K2.6. Trong MoneyPrinterTurbo, LLM của Kimi cung cấp năng lượng cho việc tạo video: viết kịch bản và trích xuất từ khóa tìm kiếm quyết định tư liệu cuối cùng, nên hiểu càng sắc nét, kết quả càng đúng chủ đề.

**MoneyPrinterTurbo đã hỗ trợ Kimi. Truy cập [Nền Tảng Mở Kimi](https://platform.kimi.ai?aff=MoneyPrinterTurbo) để thử API, hoặc khám phá [Gói Coding Plan](https://www.kimi.com/code?aff=MoneyPrinterTurbo) tiết kiệm chi phí.**

<br>
<table align="center">
  <tr>
    <td align="center" width="160">
      <a href="https://reccloud.com"><img src="docs/sponsors/reccloud-logo.svg" alt="RecCloud" height="36"></a><br>
      <a href="https://reccloud.com"><strong>RecCloud</strong></a>
    </td>
    <td align="left">
      <sub>Do việc <strong>triển khai</strong> và <strong>sử dụng</strong> dự án này có một ngưỡng nhất định đối với một số người dùng mới bắt đầu, chúng tôi đặc biệt cảm ơn <a href="https://reccloud.com">RecCloud (Nền Tảng Dịch Vụ Đa Phương Tiện được hỗ trợ bởi AI)</a> đã cung cấp dịch vụ <code>Tạo Video AI</code> miễn phí dựa trên dự án này. Cho phép sử dụng trực tuyến mà không cần triển khai, rất tiện lợi.</sub>
    </td>
  </tr>
  <tr>
    <td align="center" width="160">
      <a href="https://picwish.com"><img src="docs/sponsors/picwish-logo.svg" alt="Picwish" height="36"></a><br>
      <a href="https://picwish.com"><strong>Picwish</strong></a>
    </td>
    <td align="left">
      <sub>Cảm ơn <a href="https://picwish.com">Picwish</a> đã hỗ trợ và tài trợ cho dự án này, cho phép dự án được cập nhật và duy trì liên tục. Picwish tập trung vào <strong>lĩnh vực xử lý ảnh</strong>, cung cấp bộ công cụ <strong>xử lý ảnh</strong> phong phú, đơn giản hóa cực độ các thao tác phức tạp, thực sự làm cho việc xử lý ảnh trở nên dễ dàng hơn.</sub>
    </td>
  </tr>
</table>

## Tính Năng 🎯

- [x] Kiến trúc **MVC** hoàn chỉnh, code **cấu trúc rõ ràng**, dễ bảo trì, hỗ trợ cả `API` và `Giao diện Web`
- [x] Hỗ trợ **tạo kịch bản video tự động bằng AI**, cũng như **kịch bản tùy chỉnh**
- [x] Hỗ trợ nhiều kích thước **video độ nét cao**
  - [x] Dọc 9:16, `1080x1920`
  - [x] Ngang 16:9, `1920x1080`
- [x] Hỗ trợ **tạo video hàng loạt**, cho phép tạo nhiều video cùng lúc, sau đó chọn cái ưng ý nhất
- [x] Hỗ trợ cài đặt **thời lượng đoạn video**, thuận tiện điều chỉnh tần suất chuyển đổi tư liệu
- [x] Hỗ trợ kịch bản video bằng **Tiếng Việt**, **Tiếng Anh** và nhiều ngôn ngữ khác
- [x] Hỗ trợ **tổng hợp nhiều loại giọng nói**, có thể **nghe thử** hiệu ứng theo thời gian thực
- [x] Hỗ trợ **tạo phụ đề**, có thể điều chỉnh `phông chữ`, `vị trí`, `màu sắc`, `kích thước`, đồng thời hỗ trợ cài đặt `viền phụ đề`
- [x] Hỗ trợ **nhạc nền**, ngẫu nhiên hoặc chỉ định tệp nhạc, có thể cài đặt `âm lượng nhạc nền`
- [x] Nguồn tư liệu video **độ nét cao** và **miễn phí bản quyền**, cũng có thể dùng **tư liệu cục bộ**
- [x] Hỗ trợ nhiều nhà cung cấp tư liệu: **Pexels**, **Pixabay** và **Coverr**
- [x] Tích hợp AI video **TwelveLabs** tùy chọn: dùng embeddings **Marengo** để xếp hạng ngữ nghĩa từ khóa tìm kiếm tư liệu theo chủ đề, và **Pegasus** để QA/mô tả clip
- [x] Hỗ trợ tích hợp nhiều mô hình như **Kimi/Moonshot**, **OpenAI**, **AIHubMix**, **AIML API**, **EvoLink**, **Azure**, **one-api**, **Qwen**, **Google Gemini**, **Ollama**, **DeepSeek**, **MiniMax**, **ERNIE**, **Pollinations**, **ModelScope** và nhiều hơn nữa

## Video Demo 📺

### Dọc 9:16

<table>
<thead>
<tr>
<th align="center"><g-emoji class="g-emoji" alias="arrow_forward">▶️</g-emoji> Cách Thêm Niềm Vui Vào Cuộc Sống</th>
<th align="center"><g-emoji class="g-emoji" alias="arrow_forward">▶️</g-emoji> Ý Nghĩa Của Cuộc Sống Là Gì</th>
</tr>
</thead>
<tbody>
<tr>
<td align="center"><video src="https://github.com/harry0703/MoneyPrinterTurbo/assets/4928832/a84d33d5-27a2-4aba-8fd0-9fb2bd91c6a6"></video></td>
<td align="center"><video src="https://github.com/harry0703/MoneyPrinterTurbo/assets/4928832/112c9564-d52b-4472-99ad-970b75f66476"></video></td>
</tr>
</tbody>
</table>

### Ngang 16:9

<table>
<thead>
<tr>
<th align="center"><g-emoji class="g-emoji" alias="arrow_forward">▶️</g-emoji> Ý Nghĩa Của Cuộc Sống Là Gì</th>
<th align="center"><g-emoji class="g-emoji" alias="arrow_forward">▶️</g-emoji> Tại Sao Phải Tập Thể Dục</th>
</tr>
</thead>
<tbody>
<tr>
<td align="center"><video src="https://github.com/harry0703/MoneyPrinterTurbo/assets/4928832/346ebb15-c55f-47a9-a653-114f08bb8073"></video></td>
<td align="center"><video src="https://github.com/harry0703/MoneyPrinterTurbo/assets/4928832/271f2fae-8283-44a0-8aa0-0ed8f9a6fa87"></video></td>
</tr>
</tbody>
</table>

## Yêu Cầu Hệ Thống 📦

- Nền tảng được khuyến nghị: Windows 10+, macOS 11+, hoặc bản phân phối Linux phổ biến
- GPU không bắt buộc, nhưng được khuyến nghị nếu bạn muốn phiên âm cục bộ nhanh hơn, xử lý video nhanh hơn, hoặc trải nghiệm tạo hàng loạt mượt mà hơn

| Thành phần | Tối thiểu   | Khuyến nghị   | Lý tưởng     |
| ---------- | ----------- | ------------- | ------------ |
| CPU        | 4 nhân      | 6 đến 8 nhân  | 8+ nhân      |
| RAM        | 4 GB        | 8 GB          | 16+ GB       |
| GPU        | Không cần   | 4+ GB VRAM    | 8+ GB VRAM   |

- Nếu bạn chủ yếu dựa vào LLM đám mây, TTS đám mây và nguồn tư liệu trực tuyến, CPU và RAM quan trọng hơn GPU
- Nếu bạn dùng `faster-whisper`, tạo hàng loạt hoặc xử lý cục bộ nặng hơn, GPU sẽ cải thiện thông lượng đáng kể

## Bắt Đầu Nhanh 🚀

### Đường Dẫn Được Khuyến Nghị

- Người dùng Windows: dùng gói một cú nhấp chuột để thử nghiệm cục bộ nhanh nhất
- Người dùng MacOS / Linux: dùng `uv sync --frozen` để thiết lập cục bộ chính
- Nếu bạn muốn môi trường chạy tách biệt: dùng Docker

### Chạy Trong Google Colab

Muốn thử MoneyPrinterTurbo mà không cần thiết lập môi trường cục bộ? Chạy trực tiếp trong Google Colab!

[![Mở trong Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/harry0703/MoneyPrinterTurbo/blob/main/docs/MoneyPrinterTurbo.ipynb)

### Windows

Tải gói một cú nhấp chuột mới nhất cho Windows từ GitHub Releases, sau đó giải nén trực tiếp.

- GitHub Release: https://github.com/harry0703/MoneyPrinterTurbo/releases/latest

Sau khi tải, khuyến nghị **nhấp đúp** vào `update.bat` để cập nhật lên **code mới nhất**, sau đó nhấp đúp `start.bat` để khởi động

Sau khi khởi động, trình duyệt sẽ tự động mở (nếu mở trắng, hãy dùng **Chrome** hoặc **Edge**)

### Các Hệ Thống Khác

Chưa tạo gói khởi động một cú nhấp chuột. Xem phần **Cài Đặt & Triển Khai** bên dưới. Khuyến nghị dùng **docker** để triển khai, tiện lợi hơn.

## Cài Đặt & Triển Khai 📥

### Điều Kiện Tiên Quyết

#### ① Clone Dự Án

```shell
git clone https://github.com/harry0703/MoneyPrinterTurbo.git
```

#### ② Chỉnh Sửa Tệp Cấu Hình

- Sao chép tệp `config.example.toml` và đổi tên thành `config.toml`
- Làm theo hướng dẫn trong tệp `config.toml` để cấu hình `pexels_api_keys` và `llm_provider`, và theo nhà cung cấp dịch vụ của llm_provider, thiết lập API Key tương ứng

### Triển Khai Docker 🐳

#### ① Khởi Động Container Docker

Nếu bạn chưa cài Docker, hãy cài trước tại https://www.docker.com/products/docker-desktop/
Nếu bạn đang dùng Windows, hãy tham khảo tài liệu của Microsoft:

1. https://learn.microsoft.com/vi-vn/windows/wsl/install
2. https://learn.microsoft.com/vi-vn/windows/wsl/tutorials/wsl-containers

```shell
cd MoneyPrinterTurbo
docker compose -f docker-compose.release.yml up
```

> Mặc định được khuyến nghị là `docker-compose.release.yml`, kéo ảnh đã dựng sẵn từ GitHub Container Registry: `ghcr.io/harry0703/moneyprinterturbo:latest`.
> Nếu bạn cần dựng ảnh cục bộ, bạn vẫn có thể chạy `docker compose up`.
> Trước khi khởi động lần đầu, hãy đảm bảo `config.toml` tồn tại trong thư mục gốc của dự án. Bạn có thể sao chép từ `config.example.toml`.

#### ② Truy Cập Giao Diện Web

Mở trình duyệt và truy cập http://127.0.0.1:8501

#### ③ Truy Cập Giao Diện API

Mở trình duyệt và truy cập http://127.0.0.1:8080/docs hoặc http://127.0.0.1:8080/redoc

### Triển Khai Thủ Công 📦

#### ① Tạo Môi Trường Ảo Python

Khuyến nghị dùng [uv](https://docs.astral.sh/uv/) để quản lý môi trường Python và các phụ thuộc, với Python `3.11` làm runtime mặc định.

```shell
git clone https://github.com/harry0703/MoneyPrinterTurbo.git
cd MoneyPrinterTurbo
uv python install 3.11
uv sync --frozen
```

Nếu bạn chưa dùng `uv`, bạn vẫn có thể dùng `venv + pip`.

```shell
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Ghi chú:

- `pyproject.toml` hiện là tệp khai báo phụ thuộc chính.
- `uv.lock` ghim môi trường đã giải quyết, nên mặc định khuyến nghị dùng `uv sync --frozen`.
- `requirements.txt` chỉ giữ lại để tương thích với cách cài đặt `pip` cũ.

#### ② Khởi Động Giao Diện Web 🌐

Lưu ý cần thực hiện các lệnh sau trong `thư mục gốc` của dự án MoneyPrinterTurbo

###### Windows

```powershell
.\webui.bat
```

Bạn cũng có thể chạy `webui.bat` trong CMD.
`webui.bat` ưu tiên dùng `.venv` của dự án hoặc Python tích hợp sẵn từ gói di động. Nếu không tìm thấy Python của dự án nhưng `uv` đã được cài, nó tự động chuyển sang `uv run streamlit`.
Để cho phép các thiết bị khác trên LAN truy cập WebUI, chạy `set MPT_WEBUI_HOST=0.0.0.0` trước khi chạy `webui.bat`.

###### MacOS hoặc Linux

```shell
uv run streamlit run ./webui/Main.py --browser.gatherUsageStats=False --server.showEmailPrompt=False
```

Nếu bạn đã kích hoạt môi trường ảo thủ công, bạn vẫn có thể chạy:

```shell
sh webui.sh
```

Sau khi khởi động, trình duyệt sẽ tự động mở

#### ③ Khởi Động Dịch Vụ API 🚀

```shell
uv run python main.py
```

Nếu bạn đã kích hoạt môi trường ảo thủ công, bạn vẫn có thể chạy:

```shell
python main.py
```

#### ④ Chế Độ Dòng Lệnh Thuần Túy (Không Trình Duyệt) ⌨️

Nếu bạn không thể dùng trình duyệt hoặc chuyển tiếp cổng, bạn có thể tạo video trực tiếp từ dòng lệnh:

```shell
uv run python cli.py --video-subject "Vai Trò Của Tiền Bạc"
```

Bạn cũng có thể cung cấp tư liệu cục bộ và kiểm soát giai đoạn dừng:

```shell
uv run python cli.py \
  --video-subject "Vai Trò Của Tiền Bạc" \
  --video-source local \
  --video-materials "1.mp4,2.mp4" \
  --stop-at video
```

## Tổng Hợp Giọng Nói 🗣

Danh sách tất cả các giọng nói được hỗ trợ có thể xem tại đây: [Danh Sách Giọng Nói](./docs/voice-list.txt)

Nhà cung cấp TTS mặc định là **Edge TTS** (miễn phí, không cần API key). Trong WebUI nó hiển thị là **"Azure TTS V1"** — đây là cùng một thứ. Để chuyển đổi giọng nói, đặt `voice_name` trong `config.toml` hoặc chọn từ dropdown giọng nói trong WebUI.

> **Lưu ý:** "Azure TTS V1" (Edge TTS, miễn phí) và "Azure TTS V2" (Azure Speech SDK trả phí) là hai tùy chọn khác nhau trong WebUI. Chỉ V2 mới yêu cầu Azure API key.

Để dùng giọng nói **Azure TTS V2** chất lượng cao hơn, hãy cấu hình thông tin xác thực Azure Speech trong `config.toml`:

```toml
[azure]
speech_key = "your-azure-speech-key"
speech_region = "eastus"
```

Giọng nói Azure TTS V2 yêu cầu đăng ký [Azure Speech Services](https://portal.azure.com/). 9 giọng nói Azure được thêm vào trong v1.1.2 nghe tự nhiên hơn đáng kể so với Edge TTS trong hầu hết các trường hợp sử dụng.

## Tạo Phụ Đề 📜

Hiện có 2 cách để tạo phụ đề:

- **edge**: Dùng timestamps của Edge TTS để căn chỉnh phụ đề. Nhanh, không cần GPU, hoạt động trên mọi máy. Độ chính xác phụ thuộc vào tín hiệu thời gian TTS — đôi khi không căn chỉnh đúng với câu phức tạp.
- **whisper**: Chạy `faster-whisper` cục bộ để phiên âm audio đã tạo và tạo timestamps ở cấp độ từ. Chậm hơn (vài giây đến ~1 phút mỗi clip trên CPU tùy thuộc vào kích thước mô hình), cần tải mô hình (~250 MB cho `large-v3-turbo`, ~3 GB cho `large-v3`), nhưng tạo phụ đề chính xác hơn bất kể nhà cung cấp TTS.

Bạn có thể chuyển đổi giữa chúng bằng cách chỉnh sửa `subtitle_provider` trong tệp cấu hình `config.toml`

Khuyến nghị dùng chế độ `edge`, và chuyển sang chế độ `whisper` nếu chất lượng phụ đề tạo ra không đạt yêu cầu.

> Lưu ý:
>
> 1. Trong chế độ whisper, bạn cần tải tệp mô hình từ HuggingFace, khoảng 3GB, hãy đảm bảo kết nối internet tốt
> 2. Nếu để trống, sẽ không tạo phụ đề.

Liên kết tải mô hình (thay thế cho HuggingFace):

- Baidu Netdisk: https://pan.baidu.com/s/11h3Q6tsDtjQKTjUu3sc5cA?pwd=xjs9
- Quark Netdisk: https://pan.quark.cn/s/3ee3d991d64b

Sau khi tải mô hình, giải nén và đặt toàn bộ thư mục vào `.\MoneyPrinterTurbo\models`,
Đường dẫn tệp cuối cùng sẽ trông như thế này: `.\MoneyPrinterTurbo\models\whisper-large-v3`

```
MoneyPrinterTurbo
  ├─models
  │   └─whisper-large-v3
  │          config.json
  │          model.bin
  │          preprocessor_config.json
  │          tokenizer.json
  │          vocabulary.json
```

## Nhạc Nền 🎵

Nhạc nền cho video nằm trong thư mục `resource/songs` của dự án.

> Dự án hiện bao gồm một số nhạc mặc định từ các video YouTube. Nếu có vấn đề bản quyền, vui lòng xóa chúng đi.

## Phông Chữ Phụ Đề 🅰

Phông chữ để render phụ đề video nằm trong thư mục `resource/fonts` của dự án, bạn cũng có thể thêm phông chữ của riêng mình.

## Câu Hỏi Thường Gặp 🤔

### ❓RuntimeError: No ffmpeg exe could be found

Thông thường, ffmpeg sẽ được tải xuống tự động và phát hiện tự động.
Tuy nhiên, nếu môi trường của bạn có vấn đề ngăn việc tải xuống tự động, bạn có thể gặp lỗi sau:

```
RuntimeError: No ffmpeg exe could be found.
Install ffmpeg on your system, or set the IMAGEIO_FFMPEG_EXE environment variable.
```

Trong trường hợp này, bạn có thể tải ffmpeg từ https://www.gyan.dev/ffmpeg/builds/, giải nén và đặt `ffmpeg_path` thành đường dẫn cài đặt thực tế của bạn.

```toml
[app]
# Hãy đặt theo đường dẫn thực tế của bạn, lưu ý dấu phân cách đường dẫn Windows là \\
ffmpeg_path = "C:\\Users\\harry\\Downloads\\ffmpeg.exe"
```

### ❓Lỗi liên quan đến ImageMagick

> **Lỗi này không còn áp dụng cho phiên bản hiện tại.**
>
> Kể từ khi dự án nâng cấp lên **MoviePy 2.x**, việc render phụ đề dùng **Pillow** thay vì ImageMagick. Bạn không cần cài ImageMagick. Nếu bạn vẫn thấy lỗi này, có thể bạn đang chạy phiên bản code cũ hơn — hãy chạy `git pull` để cập nhật, hoặc dùng `update.bat` trên Windows.

### ❓OSError: [Errno 24] Too many open files

Vấn đề này do giới hạn số lượng tệp mở của hệ thống. Bạn có thể giải quyết bằng cách thay đổi giới hạn mở tệp của hệ thống.

Kiểm tra giới hạn hiện tại:

```shell
ulimit -n
```

Nếu quá thấp, bạn có thể tăng lên, ví dụ:

```shell
ulimit -n 10240
```

### ❓Tải mô hình Whisper thất bại, với lỗi sau

```
LocalEntryNotFoundError: Cannot find an appropriate cached snapshot folder for the specified revision on the local disk and
outgoing traffic has been disabled.
To enable repo look-ups and downloads online, pass 'local_files_only=False' as input.
```

hoặc

```
An error occurred while synchronizing the model Systran/faster-whisper-large-v3 from the Hugging Face Hub:
An error happened while trying to locate the files on the Hub and we cannot find the appropriate snapshot folder for the
specified revision on the local disk. Please check your internet connection and try again.
Trying to load the model directly from the local cache, if it exists.
```

Giải pháp: [Nhấn để xem cách tải mô hình thủ công từ netdisk](#tạo-phụ-đề-)

## Phản Hồi & Đề Xuất 📢

- Bạn có thể gửi [issue](https://github.com/harry0703/MoneyPrinterTurbo/issues) hoặc
  [pull request](https://github.com/harry0703/MoneyPrinterTurbo/pulls).

## Giấy Phép 📝

Nhấn để xem tệp [`LICENSE`](LICENSE)

## Lịch Sử Star

[![Star History Chart](https://api.star-history.com/svg?repos=harry0703/MoneyPrinterTurbo&type=Date)](https://star-history.com/#harry0703/MoneyPrinterTurbo&Date)
