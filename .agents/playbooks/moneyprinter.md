# Playbook: MoneyPrinterOmni via CLI

Sempre a partir da raiz do repo e dentro do dev shell:

```sh
nix develop --command bash -c '.venv/bin/python cli.py ...'
```

## 1. Teste de duração (só áudio)

```sh
.venv/bin/python cli.py --video-script "$(cat storage/projects/<slug>/script.txt)" \
  --video-language pt-BR --voice-rate 1.0 --stop-at audio
```

A última linha é um JSON com `audio_duration`. Referência: ≈ 150 palavras ≈ 60 s com
`--voice-rate 1.05` (pt-BR, en, es). Voz padrão do config: `pt-BR-AntonioNeural`. Ajuste primeiro o texto; velocidade só até ±10%.
Apague o diretório `storage/tasks/<task_id>` dos testes descartados.

### Voz em outro idioma

Passe `--video-language <locale>` e `--voice-name`. Para listar vozes Edge/Azure de um idioma:

```sh
nix develop --command .venv/bin/python -c \
  "from app.services import voice; print(voice.get_all_azure_voices(['en-US']))"
```
Ex.: `en-US-AndrewNeural-Male`, `es-ES-AlvaroNeural-Male`, `pt-BR-FranciscaNeural-Female`.

## 2. Tempos das frases

Rode `--stop-at subtitle` com o mesmo texto e velocidade, e converta a legenda:

```sh
python3 .agents/skills/video/scripts/srt_to_timing.py storage/tasks/<task_id>/subtitle.srt storage/projects/<slug>/timing.json
```
Os cortes de cena caem no início de uma frase; a duração de cada clipe vai do início da
sua primeira frase até o início da próxima cena.

## 3. Render com clipes próprios

```sh
.venv/bin/python cli.py \
  --video-script "$(cat storage/projects/<slug>/script.txt)" \
  --video-language <locale> --voice-name <voz> --voice-rate <igual ao teste> --video-aspect <formato> \
  --video-source local \
  --video-materials "$(ls storage/projects/<slug>/timeline/*.mp4 | paste -sd,)" \
  --video-concat-mode sequential --video-transition-mode none \
  --video-clip-duration <maior clipe, arredondado para cima> \
  --bgm-type custom --bgm-file <slug>.mp3 --bgm-volume 0.2   # trilha do build_music.py
```

Por que assim: em `sequential` o `combine_videos` (`app/services/video.py`) usa só os primeiros
`--video-clip-duration` segundos de cada arquivo, na ordem dada. Com clipes já cortados na
duração certa, a imagem fica sincronizada com a fala.

O JSON final traz `videos[0]` (o `final-1.mp4`). Copie para `storage/projects/<slug>/output/`.

## Sem clipes próprios

`--video-source pexels --video-terms "termo1,termo2"` e, opcionalmente,
`--match-materials-to-script`. Termos em inglês funcionam melhor no Pexels.
