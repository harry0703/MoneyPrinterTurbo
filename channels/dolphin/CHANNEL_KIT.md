# Dolphin Daily: YouTube channel kit

A Shorts channel with one short, fact-checked dolphin video a day. The 10 launch
videos are defined in [`tasks.json`](tasks.json) and rendered with MoneyPrinterTurbo
(see [Rendering the videos](#rendering-the-videos)).

## Channel identity

| Field | Value |
|---|---|
| Name | **Dolphin Daily** |
| Handle | `@DolphinDailyFacts` (backups: `@DolphinDailyShorts`, `@DailyDolphinFacts`) |
| Profile picture | [`branding/profile_800x800.png`](branding/profile_800x800.png) |
| Banner | [`branding/banner_2560x1440.png`](branding/banner_2560x1440.png). Text sits inside YouTube's 1546×423 safe area, so it shows on phones, desktops and TVs |
| Format | 9:16 vertical Shorts, about 45–55 seconds each |
| Schedule | 1 video a day. Upload all 10 at once and schedule them on consecutive days at the same hour |

The banner and profile picture are generated from [`branding/brand.html`](branding/brand.html).
To change the name or colors, edit that file and re-render it with any browser screenshot tool.

### Channel description (paste into *Customization → Basic info*)

> 🐬 One amazing dolphin fact, every day.
>
> How do dolphins sleep with half their brain? Do they really have names? Why are some
> of them pink? Dolphin Daily turns real marine-science findings into quick,
> easy-to-watch Shorts about the smartest, most social animals in the ocean.
>
> New Short every day. Subscribe and learn something new about dolphins in under a minute.

### Channel keywords (*Settings → Channel → Basic info → Keywords*)

`dolphins, dolphin facts, marine life, ocean animals, sea creatures, orca, killer whale, marine biology, animal facts, nature shorts, wildlife, ocean, bottlenose dolphin, animal shorts`

## Creating the channel (about 10 minutes)

These steps happen in your own Google account, so you have to do them yourself.

1. Sign in at <https://www.youtube.com> with the Google account you want to own the channel.
2. Click your avatar → **Create a channel**. To keep the channel separate from your
   personal name, go to <https://www.youtube.com/account> → **Create a new channel** instead.
   That creates a *Brand Account*, which you can share with managers later.
3. Enter the name **Dolphin Daily** and the handle `@DolphinDailyFacts`. If the handle is taken, use a backup.
4. Open **YouTube Studio → Customization**:
   - **Branding:** upload `profile_800x800.png` as the picture and `banner_2560x1440.png` as the banner.
   - **Basic info:** paste the description above and add your contact email if you want one.
   - **Layout:** turn on the channel trailer later. A Short can't be a trailer, so add one once you have a long video.
5. Go to **Settings → Channel → Feature eligibility** and verify your phone number.
   That unlocks custom thumbnails, videos longer than 15 minutes and live streaming.
6. Under **Settings → Upload defaults**, set a default description footer and tags
   (use the hashtags below) so each upload starts pre-filled.

## Uploading each Short

On phone or desktop, go to **Create → Upload videos**. For each video:

- **Title / description:** use the table below.
- **Audience:** pick *No, it's not made for kids* if you're aiming at a general audience,
  which is what these scripts are written for. Pick *Yes* only if kids are your main audience.
  That choice turns off comments and personalized ads, so answer honestly.
- **Altered or synthetic content:** the narration is a synthetic (text-to-speech) voice
  reading facts, and the footage is real stock video. YouTube only requires the
  disclosure for realistic content that could mislead viewers, such as a fake real person
  or a fake event, so *No* is normally correct here. Check YouTube's current policy if you're unsure.
- **Visibility:** choose *Schedule*, and set Day 1, Day 2, … at the same time each day.
  Late afternoon in your main audience's time zone is a good starting point.
- **Footage credits:** Pixabay doesn't require credit, but “Footage: Pixabay” at the
  end of the description is good practice.

Hashtags for every description: `#dolphins #dolphinfacts #oceanlife #animalfacts #shorts`

| Day | Title (≤ 100 chars) | Description (first line shows in the feed) | Extra hashtags |
|---|---|---|---|
| 1 | Dolphins Sleep With Half Their Brain 🐬 | Dolphins can't fully fall asleep, so they shut down one half of the brain at a time and keep one eye open. | #sleep #brain |
| 2 | Dolphins Have Their Own NAMES 🐬 | Every bottlenose dolphin invents a signature whistle that works like a name, and others remember it for 20+ years. | #animalcommunication |
| 3 | How Dolphins See With Sound 🔊 | Echolocation explained: clicks, the melon, and how a dolphin hears through its jaw. | #echolocation #science |
| 4 | Why Do Spinner Dolphins Spin? 🌀 | Up to seven spins in one leap. Here's what scientists think it's for. | #spinnerdolphin |
| 5 | Orcas Are Actually Dolphins 🐋 | The killer whale is the largest member of the dolphin family, and grandma is in charge. | #orca #killerwhale |
| 6 | These Dolphins Use TOOLS 🧽 | In Shark Bay, Australia, dolphins wear sea sponges on their beaks to hunt, and mothers teach their daughters. | #animalintelligence |
| 7 | How Baby Dolphins Are Born 🍼 | Tail first, a race to the surface for the first breath, and years at mom's side. | #babyanimals |
| 8 | Pink Dolphins Are Real 💗 | Meet the boto, the endangered Amazon river dolphin that swims through flooded forests. | #amazon #pinkdolphin |
| 9 | Dolphins Have to THINK to Breathe 💨 | The blowhole, the separate airway, and the 80% breath that lets dolphins dive. | #marinebiology |
| 10 | Dolphins Recognize Themselves in a Mirror 🪞 | One of the few animals to pass the mirror test, and young dolphins pass it before human toddlers do. | #mirrortest #smartanimals |

### Fact sources (for pinned comments or replies)

1. Unihemispheric sleep; 5 days of continuous echolocation vigilance: Ridgway et al., *J. Exp. Biol.* (2006), later extended to 15 days by Branstetter et al., *PLoS ONE* (2012).
2. Signature whistles answered on playback: King & Janik, *PNAS* (2013). 20-year whistle memory: Bruck, *Proc. R. Soc. B* (2013).
3. Echolocation via melon and lower jaw: Au, *The Sonar of Dolphins* (1993).
4. Spinner dolphin behavior: Norris et al., *The Hawaiian Spinner Dolphin* (1994).
5. Orcas as Delphinidae; post-reproductive grandmothers lead: Brent et al., *Current Biology* (2015).
6. Sponging in Shark Bay: Krützen et al., *PNAS* (2005). Shell “conching”: Wild et al., *Current Biology* (2020).
7. Mother and calf near-continuous activity in the first month: Lyamin et al., *Nature* (2005).
8. Boto listed Endangered: IUCN Red List (2018).
9. Breathing physiology: Ridgway, *The Bottlenose Dolphin* (1990); Fahlman et al. (2017).
10. Mirror self-recognition: Reiss & Marino, *PNAS* (2001). Early onset in calves: Morrison & Reiss, *PLoS ONE* (2018).

## Growing the channel

- **Post consistently.** Daily for the first month is the most important lever for Shorts.
- **Hook in the first 2 seconds.** Every script opens with its most surprising line. Keep that pattern for new videos.
- **Reply to comments.** Questions in the comments make good ideas for the next Shorts.
- **Add your own value.** YouTube's monetization rules (the “inauthentic content” policy)
  can block channels that only post mass-produced, template-style videos. Add a personal angle
  over time: your own commentary, a recurring series, or occasional long videos.
  This is what makes a channel eligible for the YouTube Partner Program (1,000 subscribers and
  10M Shorts views in 90 days, or 4,000 watch hours).
- **Next 10 topics:** dolphins vs. sharks, how fast dolphins swim, the vaquita (rarest
  porpoise), dolphin friendships and alliances, bubble rings, how dolphins drink water,
  dolphin teeth, Irrawaddy dolphins, dolphins helping fishermen in Laguna, Brazil, and
  how long dolphins live.

## Rendering the videos

Footage comes from Pixabay. Pexels has paused new API keys, and Pixabay
footage is also free to use in monetized YouTube videos.

1. Create a free account at <https://pixabay.com>, then open <https://pixabay.com/api/docs/>.
   While you're logged in, your key is shown in the **Parameters → key** row.
2. Add it to `config.toml`:

   ```toml
   pixabay_api_keys = ["YOUR_KEY"]
   ```

3. Render all 10 videos from the repository root:

```bash
uv run python cli.py --batch-file channels/dolphin/tasks.json --video-source pixabay --video-language en-US --voice-name en-US-AndrewNeural-Male --font-name BeVietnamPro-Bold.ttf --subtitle-position two_thirds_bottom --video-aspect 9:16 --video-transition-mode fade-in --bgm-type random --bgm-volume 0.15
```

Each finished video is written to `storage/tasks/<task-id>/final-1.mp4`. The command prints a
JSON summary that maps each manifest entry, in order, to its task ID.

**No API key at all?** Download 20–30 dolphin clips by hand from pixabay.com or pexels.com
(their websites still allow free downloads). Save them to a folder, then render with
`--video-source local --video-materials "clips/1.mp4,clips/2.mp4,..."`.
