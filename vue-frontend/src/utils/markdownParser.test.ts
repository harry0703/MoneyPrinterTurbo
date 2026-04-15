import { MarkdownParser, hasLabelMarkdown, removeLabelMarkdown } from './markdownParser.ts';

// 测试用例
const testCases = [
  {
    input: '**加粗文本**',
    expected: '<p><strong>加粗文本</strong></p>',
    description: '基本加粗格式'
  },
  {
    input: '这是**加粗**文本',
    expected: '<p>这是 <strong>加粗</strong> 文本</p>',
    description: '加粗格式与其他文本混合'
  },
  {
    input: '**龙舟水**现象',
    expected: '<p><strong>龙舟水</strong> 现象</p>',
    description: '加粗格式与相邻字符紧贴'
  },
  {
    input: '现象**龙舟水**',
    expected: '<p>现象 <strong>龙舟水</strong></p>',
    description: '加粗格式前与字符紧贴'
  },
  {
    input: '** 加粗  **',
    expected: '<p><strong>加粗</strong></p>',
    description: '加粗标记内部有空格'
  },
  {
    input: '_斜体文本_',
    expected: '<p><em>斜体文本</em></p>',
    description: '基本斜体格式'
  },
  {
    input: '这是_斜体_文本',
    expected: '<p>这是 <em>斜体</em> 文本</p>',
    description: '斜体格式与其他文本混合'
  },
  {
    input: '[链接文本](https://example.com)',
    expected: '<p><a href="https://example.com">链接文本</a></p>',
    description: '链接格式'
  },
  {
    input: '![图片描述](https://example.com/image.jpg)',
    expected: '<p><img src="https://example.com/image.jpg" alt="图片描述"></p>',
    description: '图片格式'
  },
  {
    input: '普通文本',
    expected: '<p>普通文本</p>',
    description: '无Markdown格式'
  }
];

// 运行测试
function runTests() {
  console.log('开始测试Markdown解析功能...');
  
  let passed = 0;
  let failed = 0;
  
  testCases.forEach((testCase, index) => {
    const result = MarkdownParser.parse(testCase.input);
    const success = result === testCase.expected;
    
    if (success) {
      console.log(`✓ 测试 ${index + 1}: ${testCase.description} - 通过`);
      passed++;
    } else {
      console.log(`✗ 测试 ${index + 1}: ${testCase.description} - 失败`);
      console.log(`  输入: ${testCase.input}`);
      console.log(`  期望: ${testCase.expected}`);
      console.log(`  实际: ${result}`);
      failed++;
    }
  });
  
  console.log(`\n测试结果: ${passed} 个通过, ${failed} 个失败`);
  
  // 测试其他方法
  console.log('\n测试其他方法...');
  
  // 测试hasMarkdown方法
  const markdownText = '**加粗文本**';
  const plainText = '普通文本';
  console.log(`hasMarkdown('${markdownText}'): ${hasLabelMarkdown(markdownText)}`);
  console.log(`hasMarkdown('${plainText}'): ${hasLabelMarkdown(plainText)}`);
  
  // 测试removeMarkdown方法
  const textWithMarkdown = '这是**加粗**和_斜体_文本';
  const textWithoutMarkdown = removeLabelMarkdown(textWithMarkdown);
  console.log(`removeMarkdown('${textWithMarkdown}'): ${textWithoutMarkdown}`);
  
  // 测试extractMarkdownTags方法
  const tags = MarkdownParser.extractMarkdownTags(textWithMarkdown);
  console.log(`extractMarkdownTags('${textWithMarkdown}'): ${JSON.stringify(tags)}`);
}

// 运行测试
runTests();