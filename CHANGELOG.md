<!-- insertion marker -->
## [1.1.2](https://github.com/KevinZhang19870314/MoneyPrinterTurbo/releases/tag/1.1.2) - 2024-04-18

<small>[Compare with first commit](https://github.com/KevinZhang19870314/MoneyPrinterTurbo/compare/d4f7b53b841e65da658e3d77822f9923286ddab6...1.1.2)</small>

### Features

- add support for maximum concurrency of /api/v1/videos ([abe12ab](https://github.com/KevinZhang19870314/MoneyPrinterTurbo/commit/abe12abd7b78997651468ad5dd656985066f8bd9) by kevin.zhang).
- add task deletion endpoint ([d57434e](https://github.com/KevinZhang19870314/MoneyPrinterTurbo/commit/d57434e0d31c8195dbcd3c86ff2763af96736cdf) by kevin.zhang).
- add redis support for task state management ([3d45348](https://github.com/KevinZhang19870314/MoneyPrinterTurbo/commit/3d453486627234937c7bfe6f176890360074696b) by kevin.zhang).
- enable cors to allow play video through mounted videos url ([3b1871d](https://github.com/KevinZhang19870314/MoneyPrinterTurbo/commit/3b1871d591873594bb4aa8dc17a1253b3a7563a3) by kevin.zhang).
- add /api/v1/get_bgm_list and /api/v1/upload_bgm_file ([6d8911f](https://github.com/KevinZhang19870314/MoneyPrinterTurbo/commit/6d8911f5bf496e7c5dd718309a302df88d11817b) by cathy).
- return combined videos in /api/v1/tasks response ([28199c9](https://github.com/KevinZhang19870314/MoneyPrinterTurbo/commit/28199c93b78f67e9a6bf50f290f1591078f63da8) by cathy).
- add Dockerfile ([f3b3c7f](https://github.com/KevinZhang19870314/MoneyPrinterTurbo/commit/f3b3c7fb47b01ed4ecba44eaebf29f5d6d2cb7b5) by kevin.zhang).

### Bug Fixes

- response parsing bug for gemini ([ee7306d](https://github.com/KevinZhang19870314/MoneyPrinterTurbo/commit/ee7306d216ea41e40855bbca396cacb094d572db) by elf-mouse).

### Code Refactoring

- Streaming MP4 files in the browser using video html element instead of waiting for the entire file to download before playing ([d13a3cf](https://github.com/KevinZhang19870314/MoneyPrinterTurbo/commit/d13a3cf6e911d1573c62b1f6459c3c0b7a1bc18d) by kevin.zhang).
