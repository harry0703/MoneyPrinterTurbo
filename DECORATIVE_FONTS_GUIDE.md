# Decorative Font Installation Guide

This guide will help you add artistic/decorative fonts to enhance your video titles.

## Recommended Free Fonts (All OFL Licensed - Free for Commercial Use)

### 1. Script/Handwritten Fonts

| Font Name | Style | Best For | Download Link |
|-----------|-------|----------|---------------|
| **Lobster** | Decorative script | Bold, fun titles | https://fonts.google.com/specimen/Lobster |
| **Pacifico** | Brush script | Casual, artistic titles | https://fonts.google.com/specimen/Pacifico |
| **Dancing Script** | Elegant script | Romantic, elegant titles | https://fonts.google.com/specimen/Dancing+Script |
| **Great Vibes** | Calligraphic | Formal, elegant titles | https://fonts.google.com/specimen/Great+Vibes |
| **Permanent Marker** | Hand-drawn marker | Edgy, casual titles | https://fonts.google.com/specimen/Permanent+Marker |

### 2. Bold Display Fonts

| Font Name | Style | Best For | Download Link |
|-----------|-------|----------|---------------|
| **Bebas Neue** | Tall bold | Impact headlines | https://fonts.google.com/specimen/Bebas+Neue |
| **Oswald** | Condensed bold | Strong, modern titles | https://fonts.google.com/specimen/Oswald |
| **Fredoka One** | Rounded bold | Fun, playful titles | https://fonts.google.com/specimen/Fredoka+One |
| **Righteous** | Display | Character-rich titles | https://fonts.google.com/specimen/Righteous |

### 3. Modern/Sans-Serif Fonts

| Font Name | Style | Best For | Download Link |
|-----------|-------|----------|---------------|
| **Comfortaa** | Rounded geometric | Clean, modern titles | https://fonts.google.com/specimen/Comfortaa |
| **Montserrat** | Geometric sans | Professional titles | https://fonts.google.com/specimen/Montserrat |
| **Poppins** | Geometric sans | Modern, clean titles | https://fonts.google.com/specimen/Poppins |

## Installation Steps

### Step 1: Download Fonts

1. Click on any download link above
2. On the Google Fonts page, click the "Download family" button (download icon in top-right)
3. The font will download as a ZIP file

### Step 2: Extract Font Files

1. Unzip the downloaded file
2. Look for `.ttf` or `.ttc` files (e.g., `Lobster-Regular.ttf`, `Pacifico-Regular.ttf`)
3. Copy these files to: `d:\src\MoneyPrinterTurboCN\resource\fonts\`

### Step 3: Update Font Lists

After adding fonts, update these files:

1. **Frontend** (`vue-frontend/src/views/TitleSettings.vue`):
   - Find the `availableFonts` array (around line 328)
   - Add your new font filenames

2. **Backend Style Presets** (`app/services/title_styles.py`):
   - Add new style presets using your fonts

### Example: Adding Lobster Font

After downloading `Lobster-Regular.ttf` to `resource/fonts/`:

**In TitleSettings.vue:**
```javascript
const availableFonts = [
  'MicrosoftYaHeiBold.ttc',
  'MicrosoftYaHeiNormal.ttc',
  'STHeitiLight.ttc',
  'STHeitiMedium.ttc',
  'Charm-Bold.ttf',
  'Charm-Regular.ttf',
  'UTM Kabel KT.ttf',
  'Lobster-Regular.ttf',  // ← Add this
  'Pacifico-Regular.ttf', // ← Add more as needed
];
```

## Quick Start: Essential Fonts

If you're not sure which fonts to download, start with these 5:

1. **Lobster** - Most popular decorative font
2. **Pacifico** - Beautiful handwritten style  
3. **Bebas Neue** - Bold impact font
4. **Permanent Marker** - Fun hand-drawn style
5. **Comfortaa** - Clean modern style

These give you variety: script, bold, casual, and modern styles.

## Font Usage Tips

- **Script fonts** (Lobster, Pacifico, Great Vibes): Best for short titles, not long text
- **Bold display fonts** (Bebas Neue, Oswald): Great for headlines and impact
- **Rounded fonts** (Fredoka One, Comfortaa): Friendly and approachable
- **Hand-drawn fonts** (Permanent Marker): Casual and personal feel

## License Information

All recommended fonts use the **Open Font License (OFL)**, which means:
- ✅ Free for personal use
- ✅ Free for commercial use
- ✅ Free for modification
- ❌ Cannot sell the font file itself

## Troubleshooting

### Font not showing in dropdown
- Make sure the font file is in `resource/fonts/` directory
- Check the filename matches exactly (case-sensitive)
- Restart the application

### Font not rendering correctly
- Verify the font file is not corrupted (try re-downloading)
- Check MoviePy supports the font format (`.ttf` and `.ttc` work best)
- Look for errors in the log files

### Font looks different than expected
- Some fonts have variable weights - you may need to select a specific weight file
- Font rendering depends on the operating system

## Next Steps

After installing fonts:
1. Create custom style presets in `title_styles.py`
2. Test different font combinations
3. Experiment with colors and stroke effects
4. Share your favorite combinations!
