## Subtitle Generation 📜

Currently, there are 2 ways to generate subtitles:

- edge: Faster generation speed, better performance, no specific requirements for computer configuration, but the
  quality may be unstable
- whisper: Slower generation speed, poorer performance, specific requirements for computer configuration, but more
  reliable quality

You can switch between them by modifying the `subtitle_provider` in the `config.toml` configuration file

It is recommended to use `edge` mode, and switch to `whisper` mode if the quality of the subtitles generated is not
satisfactory.

> If left blank, it means no subtitles will be generated.