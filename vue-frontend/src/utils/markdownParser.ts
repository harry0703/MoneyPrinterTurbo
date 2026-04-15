import { marked } from 'marked';

/**
 * Markdown解析工具
 * 用于识别和解析标签中的Markdown格式文字
 */
export class MarkdownParser {
  /**
   * 解析Markdown字符串
   * @param text 包含Markdown格式的文本
   * @returns 解析后的HTML
   */
  static parse(text: string): string {
    if (!text) return '';
    
    // 预处理：处理Markdown边界问题
    const processedText = this.preprocess(text);
    
    // 使用marked解析Markdown
    const result = marked.parse(processedText);
    return typeof result === 'string' ? result : '';
  }
  
  /**
   * 预处理文本，处理Markdown边界问题
   * @param text 原始文本
   * @returns 处理后的文本
   */
  private static preprocess(text: string): string {
    return text
      // 处理加粗标记与相邻字符紧贴的问题
      .replace(/([^\s*])(\*\*)([^\s*])/g, '$1 **$3')
      .replace(/(\*\*)([^\s*])([^\s*])/g, '** $2$3')
      // 处理加粗标记内部的空格
      .replace(/\*\*\s*(.+?)\s*\*\*/g, '**$1**')
      // 处理其他Markdown格式的边界问题
      .replace(/([^\s_])(_)([^\s_])/g, '$1 _$3')
      .replace(/(_)([^\s_])([^\s_])/g, '_ $2$3')
      .replace(/\s*(_)(.+?)(_)\s*/g, '_$2_');
  }
  
  /**
   * 提取文本中的Markdown标签
   * @param text 包含Markdown格式的文本
   * @returns 提取的Markdown标签数组
   */
  static extractMarkdownTags(text: string): string[] {
    const tags: string[] = [];
    
    // 提取加粗标签
    const boldTags = text.match(/\*\*(.+?)\*\*/g);
    if (boldTags) tags.push(...boldTags);
    
    // 提取斜体标签
    const italicTags = text.match(/_(.+?)_/g);
    if (italicTags) tags.push(...italicTags);
    
    // 提取链接标签
    const linkTags = text.match(/\[(.+?)\]\((.+?)\)/g);
    if (linkTags) tags.push(...linkTags);
    
    // 提取图片标签
    const imageTags = text.match(/!\[(.+?)\]\((.+?)\)/g);
    if (imageTags) tags.push(...imageTags);
    
    return tags;
  }
  
  /**
   * 检测文本是否包含Markdown格式
   * @param text 待检测的文本
   * @returns 是否包含Markdown格式
   */
  static hasMarkdown(text: string): boolean {
    if (!text) return false;
    
    // 检测常见的Markdown格式
    const markdownPatterns = [
      /\*\*[^*]+\*\*/, // 加粗
      /_[^_]+_/, // 斜体
      /\[.+?\]\(.+?\)/, // 链接
      /!\[.+?\]\(.+?\)/, // 图片
      /^# .+/m, // 标题
      /^\* .+/m, // 列表
      /^- .+/m, // 列表
      /^\d+\. .+/m, // 有序列表
      /`[^`]+`/, // 代码
      /```[\s\S]+?```/ // 代码块
    ];
    
    return markdownPatterns.some(pattern => pattern.test(text));
  }
  
  /**
   * 移除文本中的Markdown格式
   * @param text 包含Markdown格式的文本
   * @returns 移除Markdown格式后的纯文本
   */
  static removeMarkdown(text: string): string {
    if (!text) return '';
    
    return text
      // 移除加粗标记
      .replace(/\*\*(.+?)\*\*/g, '$1')
      // 移除斜体标记
      .replace(/_(.+?)_/g, '$1')
      // 移除链接标记，保留链接文本
      .replace(/\[(.+?)\]\((.+?)\)/g, '$1')
      // 移除图片标记
      .replace(/!\[(.+?)\]\((.+?)\)/g, '$1')
      // 移除标题标记
      .replace(/^#\s+/gm, '')
      // 移除列表标记
      .replace(/^\s*[*\-]\s+/gm, '')
      .replace(/^\s*\d+\.\s+/gm, '')
      // 移除代码标记
      .replace(/`([^`]+)`/g, '$1')
      .replace(/```[\s\S]+?```/g, '');
  }
}

/**
 * 解析标签中的Markdown格式
 * @param text 包含Markdown格式的标签文本
 * @returns 解析后的HTML
 */
export function parseLabelMarkdown(text: string): string {
  // 移除括号中的内容，只保留标签本身
  const labelText = text.replace(/\([^)]*\)/g, '').trim();
  return MarkdownParser.parse(labelText);
}

/**
 * 提取标签中的提示信息（括号内的内容）
 * @param text 标签文本
 * @returns 提取的提示信息
 */
export function extractLabelHint(text: string): string {
  const match = text.match(/\(([^)]*)\)/);
  return match ? match[1] : '';
}

/**
 * 检测标签是否包含Markdown格式
 * @param text 标签文本
 * @returns 是否包含Markdown格式
 */
export function hasLabelMarkdown(text: string): boolean {
  return MarkdownParser.hasMarkdown(text);
}

/**
 * 移除标签中的Markdown格式
 * @param text 包含Markdown格式的标签文本
 * @returns 移除Markdown格式后的纯文本
 */
export function removeLabelMarkdown(text: string): string {
  return MarkdownParser.removeMarkdown(text);
}