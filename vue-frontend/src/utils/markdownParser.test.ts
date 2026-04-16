import { MarkdownParser, hasLabelMarkdown, removeLabelMarkdown } from './markdownParser.ts';

// Test cases
const testCases = [
  {
    input: '**加粗文本**',
    expected: '<p><strong>加粗文本</strong></p>',
    description: 'Basic bold format'
  },
  {
    input: '这是**加粗**文本',
    expected: '<p>这是 <strong>加粗</strong> 文本</p>',
    description: 'Bold format mixed with other text'
  },
  {
    input: '**龙舟水**现象',
    expected: '<p><strong>龙舟水</strong> 现象</p>',
    description: 'Bold format adjacent to characters'
  },
  {
    input: '现象**龙舟水**',
    expected: '<p>现象 <strong>龙舟水</strong></p>',
    description: 'Bold format preceded by characters'
  },
  {
    input: '** 加粗  **',
    expected: '<p><strong>加粗</strong></p>',
    description: 'Bold markers with spaces inside'
  },
  {
    input: '_斜体文本_',
    expected: '<p><em>斜体文本</em></p>',
    description: 'Basic italic format'
  },
  {
    input: '这是_斜体_文本',
    expected: '<p>这是 <em>斜体</em> 文本</p>',
    description: 'Italic format mixed with other text'
  },
  {
    input: '[链接文本](https://example.com)',
    expected: '<p><a href="https://example.com">链接文本</a></p>',
    description: 'Link format'
  },
  {
    input: '![图片描述](https://example.com/image.jpg)',
    expected: '<p><img src="https://example.com/image.jpg" alt="图片描述"></p>',
    description: 'Image format'
  },
  {
    input: '普通文本',
    expected: '<p>普通文本</p>',
    description: 'No Markdown format'
  }
];

// Run tests
function runTests() {
  console.log('Starting Markdown parsing tests...');
  
  let passed = 0;
  let failed = 0;
  
  testCases.forEach((testCase, index) => {
    const result = MarkdownParser.parse(testCase.input);
    const success = result === testCase.expected;
    
    if (success) {
      console.log(`✓ Test ${index + 1}: ${testCase.description} - Passed`);
      passed++;
    } else {
      console.log(`✗ Test ${index + 1}: ${testCase.description} - Failed`);
      console.log(`  Input: ${testCase.input}`);
      console.log(`  Expected: ${testCase.expected}`);
      console.log(`  Actual: ${result}`);
      failed++;
    }
  });
  
  console.log(`\nTest results: ${passed} passed, ${failed} failed`);
  
  // Test other methods
  console.log('\nTesting other methods...');
  
  // Test hasMarkdown method
  const markdownText = '**加粗文本**';
  const plainText = '普通文本';
  console.log(`hasMarkdown('${markdownText}'): ${hasLabelMarkdown(markdownText)}`);
  console.log(`hasMarkdown('${plainText}'): ${hasLabelMarkdown(plainText)}`);
  
  // Test removeMarkdown method
  const textWithMarkdown = '这是**加粗**和_斜体_文本';
  const textWithoutMarkdown = removeLabelMarkdown(textWithMarkdown);
  console.log(`removeMarkdown('${textWithMarkdown}'): ${textWithoutMarkdown}`);
  
  // Test extractMarkdownTags method
  const tags = MarkdownParser.extractMarkdownTags(textWithMarkdown);
  console.log(`extractMarkdownTags('${textWithMarkdown}'): ${JSON.stringify(tags)}`);
}

// Run tests
runTests();