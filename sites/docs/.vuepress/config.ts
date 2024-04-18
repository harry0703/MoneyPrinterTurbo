import { viteBundler } from "@vuepress/bundler-vite";
import { defaultTheme } from "@vuepress/theme-default";
import { defineUserConfig } from "vuepress";

const __dirname = process.cwd();

const base = "money-printer-turbo";
const isProd = process.env.NODE_ENV === "production";

export default defineUserConfig({
  lang: "zh-CN",
  base: `/${base}/`,
  bundler: viteBundler(),
  theme: defaultTheme({
    repo: "harry0703/MoneyPrinterTurbo/sites",
    docsDir: "docs",
    colorModeSwitch: false,
    locales: {
      "/": {
        // navbar
        navbar: [
          { text: "Guide", link: "/guide/" },
          { text: "Components", link: "/components/" },
        ],
        selectLanguageText: "Languages",
        selectLanguageName: "English",
        selectLanguageAriaLabel: "Select language",
        // sidebar
        sidebar: {
          "/guide/": getGuideSidebar("Guide", "Advanced"),
          "/components/": getComponentsSidebar("Components", "Advanced"),
        },
        // page meta
        editLinkText: "Edit this page on GitHub",
      },
      "/zh/": {
        // navbar
        navbar: [
          { text: "指南", link: "/zh/guide/" },
          { text: "组件", link: "/zh/components/" },
        ],
        selectLanguageText: "选择语言",
        selectLanguageName: "简体中文",
        selectLanguageAriaLabel: "选择语言",
        // sidebar
        sidebar: {
          "/zh/guide/": getGuideSidebar("指南", "深入"),
          "/zh/components/": getComponentsSidebar("组件", "高级"),
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
      children: ["README.md", "1.md", "2.md"],
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
