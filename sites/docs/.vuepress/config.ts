import { viteBundler } from "@vuepress/bundler-vite";
import { defaultTheme } from "@vuepress/theme-default";
import { defineUserConfig } from "vuepress";

const base = "MoneyPrinterTurbo";
const isProd = process.env.NODE_ENV === "production";

export default defineUserConfig({
  lang: "zh-CN",
  base: `/${base}/`,
  bundler: viteBundler(),
  theme: defaultTheme({
    repo: "harry0703/MoneyPrinterTurbo",
    docsDir: "sites/docs",
    colorModeSwitch: true,
    locales: {
      "/": {
        // navbar
        navbar: [
          { text: "Guide", link: "/guide/" },
          // { text: "Components", link: "/components/" },
        ],
        selectLanguageText: "Languages",
        selectLanguageName: "English",
        selectLanguageAriaLabel: "Select language",
        // sidebar
        sidebar: {
          "/guide/": [
            {
              text: "Guide",
              children: [
                { text: "Get Started", link: "/guide/README.md" }, 
                { text: "Video Demonstration", link: "/guide/video-demonstration.md" },
                { text: "Features", link: "/guide/features.md" },
                { text: "Speech Synthesis", link: "/guide/speech-synthesis.md" },
                { text: "Subtitle Generation", link: "/guide/subtitle-generation.md" },
                { text: "Background Music", link: "/guide/background-music.md" },
                { text: "Subtitle Font", link: "/guide/subtitle-font.md" },
              ],
            },
            {
              text: "Others",
              children: [
                { text: "FAQ", link: "/guide/faq.md" },
                { text: "Feedback", link: "/guide/feedback.md" },
                { text: "Reference Project", link: "/guide/reference-project.md" },
              ],
            },
          ],
          // "/components/": getComponentsSidebar("Components", "Advanced"),
        },
        // page meta
        editLinkText: "Edit this page on GitHub",
      },
      "/zh/": {
        // navbar
        navbar: [
          { text: "指南", link: "/zh/guide/" },
          // { text: "组件", link: "/zh/components/" },
        ],
        selectLanguageText: "选择语言",
        selectLanguageName: "简体中文",
        selectLanguageAriaLabel: "选择语言",
        // sidebar
        sidebar: {
          "/zh/guide/": [
            {
              text: "指南",
              children: [
                { text: "快速开始", link: "/zh/guide/README.md" }, 
                { text: "配置要求", link: "/zh/guide/configuration-requirements.md" },
                { text: "视频演示", link: "/zh/guide/video-demonstration.md" },
                { text: "功能", link: "/zh/guide/features.md" },
                { text: "语音合成", link: "/zh/guide/speech-synthesis.md" },
                { text: "字幕生成", link: "/zh/guide/subtitle-generation.md" },
                { text: "背景音乐", link: "/zh/guide/background-music.md" },
                { text: "字幕字体", link: "/zh/guide/subtitle-font.md" },
              ],
            },
            {
              text: "其他",
              children: [
                { text: "常见问题", link: "/zh/guide/faq.md" },
                { text: "反馈建议", link: "/zh/guide/feedback.md" },
                { text: "参考项目", link: "/zh/guide/reference-project.md" },
                { text: "特别感谢", link: "/zh/guide/special-thanks.md" }, 
                { text: "感谢赞助", link: "/zh/guide/thanks-for-sponsoring" },
              ],
            },
          ],
          // "/zh/others/": getComponentsSidebar("组件", "高级"),
        },
        // page meta
        editLinkText: "在 GitHub 上编辑此页",
        lastUpdatedText: "上次更新",
        contributorsText: "贡献者",
        // custom containers
        tip: "提示",
        warning: "注意",
        danger: "警告",
        // 404 page
        notFound: [
          "这里什么都没有",
          "我们怎么到这来了？",
          "这是一个 404 页面",
          "看起来我们进入了错误的链接",
        ],
        backToHome: "返回首页",
      },
    },
    themePlugins: {
      // only enable git plugin in production mode
      git: isProd,
    },
  }),
  locales: {
    "/": {
      lang: "en-US",
      title: "MoneyPrinterTurbo",
      description: "Generate short videos with one click using AI LLM.",
    },
    "/zh/": {
      lang: "zh-CN",
      title: "MoneyPrinterTurbo",
      description: "利用AI大模型，一键生成高清短视频。",
    },
  },
  head: [
    [
      "link",
      {
        rel: "icon",
        type: "image/png",
        sizes: "16x16",
        href: `/${base}/icons/favicon-16x16.png`,
      },
    ],
    [
      "link",
      {
        rel: "icon",
        type: "image/png",
        sizes: "32x32",
        href: `/${base}/icons/favicon-32x32.png`,
      },
    ],
    ["meta", { name: "application-name", content: "MoneyPrinterTurbo" }],
    [
      "meta",
      { name: "apple-mobile-web-app-title", content: "MoneyPrinterTurbo" },
    ],
    ["meta", { name: "apple-mobile-web-app-capable", content: "yes" }],
    [
      "meta",
      { name: "apple-mobile-web-app-status-bar-style", content: "black" },
    ],
    [
      "link",
      {
        rel: "apple-touch-icon",
        href: `/${base}/icons/apple-touch-icon-152x152.png`,
      },
    ],
    [
      "link",
      {
        rel: "mask-icon",
        href: "/${base}/icons/safari-pinned-tab.svg",
        color: "#3eaf7c",
      },
    ],
    [
      "meta",
      {
        name: "msapplication-TileImage",
        content: "/${base}/icons/msapplication-icon-144x144.png",
      },
    ],
    ["meta", { name: "msapplication-TileColor", content: "#000000" }],
    ["meta", { name: "theme-color", content: "#3eaf7c" }],
  ],
});

function getGuideSidebar(groupA: string, groupB: string) {
  return [
    {
      text: groupA,
      children: ["README.md", { text: "特别感谢", link: "/zh/guide/special-thanks.md" }, "2.md"],
    },
    {
      text: groupB,
      children: ["custom-validator.md", "1.md", "2.md", "3.md"],
    },
  ];
}

function getComponentsSidebar(groupA: string, groupB: string) {
  return [
    {
      text: groupA,
      children: ["README.md", "1.md", "2.md"],
    },
    {
      text: groupB,
      children: ["custom-components.md"],
    },
  ];
}
