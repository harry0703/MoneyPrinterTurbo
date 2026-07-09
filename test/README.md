# Thư Mục Test của MoneyPrinterTurbo

Thư mục này chứa các unit test cho dự án **MoneyPrinterTurbo**.

## Cấu Trúc Thư Mục

- `services/`: Các test cho các component trong thư mục `app/services`
  - `test_video.py`: Các test cho dịch vụ video
  - `test_task.py`: Các test cho dịch vụ tác vụ
  - `test_voice.py`: Các test cho dịch vụ giọng nói

## Chạy Test

Bạn có thể chạy các test bằng framework `unittest` tích hợp sẵn của Python:

```bash
# Chạy tất cả các test
python -m unittest discover -s test

# Chạy một tệp test cụ thể
python -m unittest test/services/test_video.py

# Chạy một lớp test cụ thể
python -m unittest test.services.test_video.TestVideoService

# Chạy một phương thức test cụ thể
python -m unittest test.services.test_video.TestVideoService.test_preprocess_video
```

Các test nhà cung cấp trực tiếp bị bỏ qua theo mặc định. Để chạy các test có thể gọi dịch vụ TTS hoặc LLM bên ngoài, đặt `MPT_RUN_INTEGRATION_TESTS=1` và cung cấp thông tin xác thực nhà cung cấp cần thiết.

## Thêm Test Mới

Để thêm test cho các component khác, hãy làm theo các hướng dẫn sau:

1. Tạo các tệp test có tiền tố `test_` trong thư mục con phù hợp
2. Dùng `unittest.TestCase` làm lớp cơ sở cho các lớp test của bạn
3. Đặt tên các phương thức test với tiền tố `test_`

## Tài Nguyên Test

Đặt bất kỳ tệp tài nguyên nào cần thiết cho việc test vào thư mục `test/resources`.
