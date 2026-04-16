import { marked } from 'marked';

/**
 * Markdown parsing utility
 * Used to identify and parse Markdown formatted text in labels
 */
export class MarkdownParser {
  /**
   * Parse Markdown string
   * @param text Text containing Markdown format
   * @returns Parsed HTML
   */
  static parse(text: string): string {
    if (!text) return '';
    
    // Preprocess: handle Markdown boundary issues
    const processedText = this.preprocess(text);
    
    // Use marked to parse Markdown
    const result = marked.parse(processedText);
    return typeof result === 'string' ? result : '';
  }
  
  /**
   * Preprocess text, handle Markdown boundary issues
   * @param text Original text
   * @returns Processed text
   */
  private static preprocess(text: string): string {
    return text
      // Handle color syntax :blue[content]
      .replace(/:([a-zA-Z]+)\[([^\]]+)\]/g, '<span style="color: $1;">$2</span>')
      // Handle bold markers adjacent to characters
      .replace(/([^\s*])(\*\*)([^\s*])/g, '$1 **$3')
      .replace(/(\*\*)([^\s*])([^\s*])/g, '** $2$3')
      // Handle spaces inside bold markers
      .replace(/\*\*\s*(.+?)\s*\*\*/g, '**$1**')
      // Handle other Markdown format boundary issues
      .replace(/([^\s_])(_)([^\s_])/g, '$1 _$3')
      .replace(/(_)([^\s_])([^\s_])/g, '_ $2$3')
      .replace(/\s*(_)(.+?)(_)\s*/g, '_$2_');
  }
  
  /**
   * Extract Markdown tags from text
   * @param text Text containing Markdown format
   * @returns Array of extracted Markdown tags
   */
  static extractMarkdownTags(text: string): string[] {
    const tags: string[] = [];
    
    // Extract bold tags
    const boldTags = text.match(/\*\*(.+?)\*\*/g);
    if (boldTags) tags.push(...boldTags);
    
    // Extract italic tags
    const italicTags = text.match(/_(.+?)_/g);
    if (italicTags) tags.push(...italicTags);
    
    // Extract link tags
    const linkTags = text.match(/\[(.+?)\]\((.+?)\)/g);
    if (linkTags) tags.push(...linkTags);
    
    // Extract image tags
    const imageTags = text.match(/!\[(.+?)\]\((.+?)\)/g);
    if (imageTags) tags.push(...imageTags);
    
    return tags;
  }
  
  /**
   * Check if text contains Markdown format
   * @param text Text to check
   * @returns Whether it contains Markdown format
   */
  static hasMarkdown(text: string): boolean {
    if (!text) return false;
    
    // Check common Markdown formats
    const markdownPatterns = [
      /\*\*[^*]+\*\*/, // Bold
      /_[^_]+_/, // Italic
      /\[.+?\]\(.+?\)/, // Link
      /!\[.+?\]\(.+?\)/, // Image
      /^# .+/m, // Heading
      /^\* .+/m, // List
      /^- .+/m, // List
      /^\d+\. .+/m, // Ordered list
      /`[^`]+`/, // Code
      /```[\s\S]+?```/ // Code block
    ];
    
    return markdownPatterns.some(pattern => pattern.test(text));
  }
  
  /**
   * Remove Markdown format from text
   * @param text Text containing Markdown format
   * @returns Plain text without Markdown format
   */
  static removeMarkdown(text: string): string {
    if (!text) return '';
    
    return text
      // Remove bold markers
      .replace(/\*\*(.+?)\*\*/g, '$1')
      // Remove italic markers
      .replace(/_(.+?)_/g, '$1')
      // Remove link markers, keep link text
      .replace(/\[(.+?)\]\((.+?)\)/g, '$1')
      // Remove image markers
      .replace(/!\[(.+?)\]\((.+?)\)/g, '$1')
      // Remove heading markers
      .replace(/^#\s+/gm, '')
      // Remove list markers
      .replace(/^\s*[*\-]\s+/gm, '')
      .replace(/^\s*\d+\.\s+/gm, '')
      // Remove code markers
      .replace(/`([^`]+)`/g, '$1')
      .replace(/```[\s\S]+?```/g, '');
  }
}

/**
 * Parse Markdown format in labels
 * @param text Label text containing Markdown format
 * @returns Parsed HTML
 */
export function parseLabelMarkdown(text: string): string {
  // Remove content in parentheses, only keep the label itself
  const labelText = text.replace(/\([^)]*\)/g, '').trim();
  return MarkdownParser.parse(labelText);
}

/**
 * Extract hint information from labels (content in parentheses)
 * @param text Label text
 * @returns Extracted hint information
 */
export function extractLabelHint(text: string): string {
  const match = text.match(/\(([^)]*)\)/);
  return match ? match[1] : '';
}

/**
 * Check if label contains Markdown format
 * @param text Label text
 * @returns Whether it contains Markdown format
 */
export function hasLabelMarkdown(text: string): boolean {
  return MarkdownParser.hasMarkdown(text);
}

/**
 * Remove Markdown format from labels
 * @param text Label text containing Markdown format
 * @returns Plain text without Markdown format
 */
export function removeLabelMarkdown(text: string): string {
  return MarkdownParser.removeMarkdown(text);
}