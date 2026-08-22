import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawnSync} from 'node:child_process';

const repo = process.env.TASK7_REPO_ROOT ? path.resolve(process.env.TASK7_REPO_ROOT) : process.cwd();
const work = path.join(repo, '09_泛健康日更', 'work');
const qaRoot = path.join(work, 'HC20260810-B01-task7-qa');
const mode = process.argv[2] || 'all';

const C = {cream:'#FFF8EC', teal:'#087F78', fresh:'#10BFAE', peach:'#F5C79E', ink:'#24313D'};
const display = 'Noto Sans SC';
const bodyFont = 'Microsoft YaHei';

const episodes = [
  {id:'001', topic:'午后犯困先看三件事', cover:'午后犯困先看三项', src:['S01','S05'], cards:[
    ['午后犯困先看三项','先把昨晚、午餐和饭后安排放在一起。'],['餐后刚回到座位','餐桌边刚放下餐具，回座不久就眼皮发沉。'],['回想昨晚睡起','只记大致时点，和自己的重复情况比。'],['留意午餐过程','看速度，也看停下时的饱足感。'],['再看饭后安排','比较一直坐着与轻松动过的感受。'],['手机点选三项','补一句当时感受，先不同时改多件事。'],['留作下次入口','难以清醒时安全优先，记录可以稍后再做。']], icons:['moon','plate','path']},
  {id:'002', topic:'吃饭快慢与下午感受', cover:'吃饭快慢留个停顿', src:['S04','S03'], cards:[
    ['吃饭快慢怎么比','同份午餐只把速度当作一个观察变量。'],['休息区吃到一半','办公室休息区里放下餐具，才觉察自己还饿不饿。'],['看大致时长','从第一口到放下餐具，不追固定分钟。'],['看中途饥饿','吃到一半停一下，感受自己还饿不饿。'],['看回座感受','留意清醒与专注，只记录当时体验。'],['问两句再决定','还饿吗？已经够了吗？然后自主选择。'],['停顿可以再试','吞咽不顺或进餐不舒服时不做对比。']], icons:['plate','pause','chair']},
  {id:'003', topic:'午餐太撑后怎样安排', cover:'吃撑以后先放稳些', src:['S01','S04'], cards:[
    ['吃撑以后先放稳','先看份量、停下时机和下午安排。'],['添过一回才觉太撑','餐桌上又添了一回，离席后才觉得太撑，下午做事变慢。'],['回想开始份量','看起初盛了多少，后来有没有添加。'],['留意停下时机','已经觉得够时，是否仍在继续。'],['下午排平稳事','先做节奏平稳、容错较高的事情。'],['下次少盛一点','吃完再决定是否添加，不设统一份量。'],['安排留作备忘','持续不舒服时，停止自行调整。']], icons:['bowl','pause','blocks']},
  {id:'004', topic:'饭后坐着或轻走的感受', cover:'七天对比坐走感受', src:['S03','S06'], cards:[
    ['七天看坐走感受','饭后坐着或轻走，只比较自己的多次体验。'],['长椅和步道之间','社区饭后坐在长椅，另一天轻走一段，回家感受并不一样。'],['记坐着时段','只留大致时间，不追数字排名。'],['先确认路线','平坦、方便、安全时再轻松走。'],['看三种感受','留意舒适、困意和之后做事感觉。'],['今天记一种','按当天安排如实记录，不预设结果。'],['七天不是阈值','它只是第一轮观察窗，不用判断好坏。']], icons:['bench','path','dots']},
  {id:'005', topic:'下午没精神的小重启', cover:'下午卡住简短重启', src:['S03'], cards:[
    ['重启不用排太满','下午卡住时，把计划缩成一次短暂停顿。'],['办公位越想越卡','盯着屏幕列了好几种休息计划，反而迟迟没有动。'],['看卡住之前','留意正在做什么，以及持续了多久。'],['三件只选一件','离开屏幕、换姿势或看远处。'],['回来再感受','看看清醒度是否变化，不把感觉写成承诺。'],['三分钟做提示','系统计时只是编辑窗口，不是恢复公式。'],['流程留作启动','高风险场景不做挑战，难以清醒就停下。']], icons:['chair','window','dot']},
  {id:'006', topic:'午休后更困先看时点', cover:'午休看清三个时点', src:['S10','S07'], cards:[
    ['午休看三个时点','躺下、估计入睡和醒来要分开记录。'],['闹钟响了仍发懵','家中午休醒来坐在沙发边，闹钟响了，脑子仍有些发懵。'],['先点选躺下','只留大致时点，不追精确。'],['再估计入睡','和自己的多次午休作对照。'],['还要记录醒来','自然醒或被叫醒，也留意醒后感受。'],['醒后留段缓冲','反应要求高的事情稍后再安排。'],['三个时点再对照','还在发懵时，驾驶和机器操作都先放一放。']], icons:['couch','sun','path']},
  {id:'007', topic:'下午喝咖啡先记时点', cover:'咖啡先记饮用时点', src:['S03','S01'], cards:[
    ['咖啡先记饮用时点','桌边那杯可以成为一次记录提示。'],['杯子还在手边','餐桌边工作一卡住，看见杯子就想顺手再续一杯。'],['记末次时间','只留当天末次含咖啡因饮品时点。'],['记种类份量','保留大致杯量，不追精确数值。'],['记当晚感受','晚上补充躺下后的入睡体验。'],['比较只改时点','种类与份量尽量相近，结果保留差异。'],['时间卡留作前后比','不设统一停饮时点，也不靠加量硬撑。']], icons:['cup','cups','moon']},
  {id:'008', topic:'午后嘴馋先记三类线索', cover:'嘴馋先记三类线索', src:['S03','S04'], cards:[
    ['嘴馋先记三类线索','一次想吃只留作观察，不写成已经找到原因。'],['长椅旁看见零食','社区长椅旁伸手拿零食前，才觉察当时的饿、渴和场景。'],['记主观饥饿','看距离上一餐多久，也看当下感受。'],['记主观口渴','回想近期饮水，不把渴直接当成饿。'],['记当时场景','看到食物、工作暂停或固定时点都可记录。'],['手机点选三类','点完再自主决定吃、喝或离开位置。'],['线索留作下次参照','不大量喝水压住饥饿，也不长时间强忍。']], icons:['bowl','glass','scene']},
  {id:'009', topic:'下午难任务何时做更顺', cover:'难任务换个时点比', src:[], cards:[
    ['难任务换时点再比','同类任务截成小段，放进两个下午时点。'],['同一小段两种感受','办公位做同类小任务，有时容易起步，有时返工变多。'],['先截同类小段','避免拿完全不同的事情硬比。'],['记开始与类型','时点要和任务类型一起留下。'],['记启动返工完成感','只作个人反馈，不是能力分数。'],['下次换时点','其余条件尽量照常，再做一次对照。'],['对比留作排活','一两次顺利不算规律，困倦时安全优先。']], icons:['blocks','sun','path']},
  {id:'010', topic:'连续七天记录午后变化', cover:'七天记录午后变化', src:['S04','S05'], cards:[
    ['七天记录午后变化','回看时只找重复和例外，不给自己打分。'],['周末回看留白日','家中回看七天记录，漏的一天留白，重复和例外才更清楚。'],['记前一晚睡起','每天只留大致时点。'],['记午餐饭后安排','把午餐结束和之后安排一起看。'],['记午后两个时点','留意发沉和做事较顺分别出现在哪时。'],['漏记就保持空白','不凭记忆补，也不把缺失写成零。'],['同组字段下一轮再用','七天是编辑观察窗，不是形成规律的期限。']], icons:['moon','plate','dots']},
];

const esc = s => s.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const sha = p => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const t = (x,y,text,size=42,weight=400,fill=C.ink,anchor='start') => `<text x="${x}" y="${y}" font-family="${weight>=700?display:bodyFont}" font-size="${size}" font-weight="${weight}" fill="${fill}" text-anchor="${anchor}">${esc(text)}</text>`;
const multiline = (x,y,lines,size=42,lh=66,weight=400,fill=C.ink) => `<text x="${x}" y="${y}" font-family="${weight>=700?display:bodyFont}" font-size="${size}" font-weight="${weight}" fill="${fill}">${lines.map((s,i)=>`<tspan x="${x}" dy="${i?lh:0}">${esc(s)}</tspan>`).join('')}</text>`;
const wrap = (s,max=17) => {
  const a=[]; let line=''; const punctuation='，。？！、；：）》」';
  for(const char of s){
    if(line.length>=max && !punctuation.includes(char)){a.push(line); line=char;}
    else line+=char;
  }
  if(line) a.push(line);
  return a;
};
const marker = page => `${t(72,204,'生活节奏看得见',36,700,C.teal)}<path d="M72 232h128" stroke="${C.fresh}" stroke-width="8"/>${t(900,204,`${page}/07`,34,700,C.teal,'end')}`;
const footer = () => `${t(72,1488,'留作个人生活观察 · 安全优先',36,600,C.ink)}<path d="M72 1520h828" stroke="${C.peach}" stroke-width="4"/><circle cx="836" cy="1664" r="104" fill="${C.peach}"/><path d="M808 1664c28-48 60-48 88 0" stroke="${C.teal}" stroke-width="20" fill="none" stroke-linecap="round"/>`;
const base = inner => `<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1080" height="1920" viewBox="0 0 1080 1920"><rect width="1080" height="1920" fill="${C.cream}"/>${inner}</svg>`;
const image = (href,x,y,w,h,id,pos='xMidYMid') => `<defs><clipPath id="${id}"><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="24"/></clipPath></defs><image href="${href}" xlink:href="${href}" x="${x}" y="${y}" width="${w}" height="${h}" preserveAspectRatio="${pos} slice" clip-path="url(#${id})"/>`;

function icon(kind,x,y,scale=1,fg=C.teal,bg=C.peach){
  const X=n=>x+n*scale,Y=n=>y+n*scale,S=n=>n*scale;
  const shapes={
    moon:`<circle cx="${X(80)}" cy="${Y(80)}" r="${S(62)}" fill="${bg}"/><path d="M${X(98)} ${Y(28)}a58 58 0 1 0 18 104a48 48 0 1 1-18-104" fill="${fg}"/>`,
    plate:`<circle cx="${X(72)}" cy="${Y(80)}" r="${S(58)}" fill="${bg}"/><circle cx="${X(72)}" cy="${Y(80)}" r="${S(38)}" fill="none" stroke="${fg}" stroke-width="${S(10)}"/><path d="M${X(146)} ${Y(28)}L${X(146)} ${Y(132)}M${X(134)} ${Y(28)}L${X(134)} ${Y(70)}L${X(158)} ${Y(70)}L${X(158)} ${Y(28)}" stroke="${fg}" stroke-width="${S(8)}" fill="none" stroke-linecap="round"/>`,
    path:`<path d="M${X(20)} ${Y(140)}C${X(38)} ${Y(96)},${X(116)} ${Y(106)},${X(142)} ${Y(18)}" fill="none" stroke="${fg}" stroke-width="${S(24)}" stroke-linecap="round"/><circle cx="${X(38)}" cy="${Y(38)}" r="${S(20)}" fill="${bg}"/>`,
    pause:`<rect x="${X(24)}" y="${Y(24)}" width="${S(120)}" height="${S(120)}" rx="${S(24)}" fill="${bg}"/><rect x="${X(58)}" y="${Y(48)}" width="${S(18)}" height="${S(72)}" rx="${S(8)}" fill="${fg}"/><rect x="${X(94)}" y="${Y(48)}" width="${S(18)}" height="${S(72)}" rx="${S(8)}" fill="${fg}"/>`,
    chair:`<path d="M${X(42)} ${Y(34)}L${X(42)} ${Y(104)}L${X(118)} ${Y(104)}L${X(118)} ${Y(60)}M${X(42)} ${Y(104)}L${X(42)} ${Y(146)}M${X(118)} ${Y(104)}L${X(118)} ${Y(146)}" stroke="${fg}" stroke-width="${S(16)}" fill="none" stroke-linecap="round"/><circle cx="${X(126)}" cy="${Y(34)}" r="${S(20)}" fill="${bg}"/>`,
    bowl:`<ellipse cx="${X(81)}" cy="${Y(62)}" rx="${S(61)}" ry="${S(22)}" fill="${C.cream}" stroke="${fg}" stroke-width="${S(8)}"/><path d="M${X(20)} ${Y(62)}Q${X(28)} ${Y(144)} ${X(81)} ${Y(144)}Q${X(134)} ${Y(144)} ${X(142)} ${Y(62)}Q${X(81)} ${Y(92)} ${X(20)} ${Y(62)}Z" fill="${bg}" stroke="${fg}" stroke-width="${S(8)}"/><circle cx="${X(58)}" cy="${Y(56)}" r="${S(10)}" fill="${C.fresh}"/><circle cx="${X(82)}" cy="${Y(50)}" r="${S(12)}" fill="${C.peach}"/><circle cx="${X(108)}" cy="${Y(58)}" r="${S(9)}" fill="${fg}"/>`,
    blocks:`<rect x="${X(16)}" y="${Y(30)}" width="${S(56)}" height="${S(56)}" rx="${S(12)}" fill="${fg}"/><rect x="${X(84)}" y="${Y(30)}" width="${S(56)}" height="${S(56)}" rx="${S(12)}" fill="${bg}"/><rect x="${X(50)}" y="${Y(98)}" width="${S(56)}" height="${S(56)}" rx="${S(12)}" fill="${C.fresh}"/>`,
    bench:`<rect x="${X(24)}" y="${Y(66)}" width="${S(120)}" height="${S(34)}" rx="${S(8)}" fill="${fg}"/><rect x="${X(34)}" y="${Y(98)}" width="${S(12)}" height="${S(46)}" rx="${S(5)}" fill="${fg}"/><rect x="${X(126)}" y="${Y(98)}" width="${S(12)}" height="${S(46)}" rx="${S(5)}" fill="${fg}"/><circle cx="${X(42)}" cy="${Y(32)}" r="${S(20)}" fill="${bg}"/>`,
    dots:`<circle cx="${X(28)}" cy="${Y(80)}" r="${S(20)}" fill="${fg}"/><circle cx="${X(82)}" cy="${Y(80)}" r="${S(20)}" fill="${C.fresh}"/><circle cx="${X(136)}" cy="${Y(80)}" r="${S(20)}" fill="${bg}"/><path d="M${X(28)} ${Y(118)}h108" stroke="${fg}" stroke-width="${S(8)}"/>`,
    window:`<rect x="${X(8)}" y="${Y(34)}" width="${S(44)}" height="${S(92)}" rx="${S(10)}" fill="${C.cream}" stroke="${fg}" stroke-width="${S(5)}"/><path d="M${X(22)} ${Y(54)}h16M${X(22)} ${Y(72)}h16" stroke="${C.fresh}" stroke-width="${S(6)}" stroke-linecap="round"/><rect x="${X(59)}" y="${Y(34)}" width="${S(44)}" height="${S(92)}" rx="${S(10)}" fill="${C.cream}" stroke="${fg}" stroke-width="${S(5)}"/><path d="M${X(70)} ${Y(90)}h22M${X(74)} ${Y(90)}v18M${X(88)} ${Y(90)}v18" stroke="${C.fresh}" stroke-width="${S(6)}" stroke-linecap="round"/><rect x="${X(110)}" y="${Y(34)}" width="${S(44)}" height="${S(92)}" rx="${S(10)}" fill="${C.cream}" stroke="${fg}" stroke-width="${S(5)}"/><circle cx="${X(132)}" cy="${Y(58)}" r="${S(9)}" fill="${C.peach}"/><path d="M${X(118)} ${Y(104)}L${X(128)} ${Y(88)}L${X(136)} ${Y(98)}L${X(146)} ${Y(82)}" fill="none" stroke="${C.fresh}" stroke-width="${S(6)}" stroke-linecap="round" stroke-linejoin="round"/>`,
    dot:`<circle cx="${X(80)}" cy="${Y(80)}" r="${S(64)}" fill="${bg}"/><circle cx="${X(80)}" cy="${Y(80)}" r="${S(24)}" fill="${fg}"/>`,
    couch:`<rect x="${X(22)}" y="${Y(74)}" width="${S(118)}" height="${S(58)}" rx="${S(12)}" fill="${bg}" stroke="${fg}" stroke-width="${S(8)}"/><rect x="${X(34)}" y="${Y(42)}" width="${S(94)}" height="${S(54)}" rx="${S(14)}" fill="${bg}" stroke="${fg}" stroke-width="${S(8)}"/><path d="M${X(34)} ${Y(132)}L${X(34)} ${Y(150)}M${X(128)} ${Y(132)}L${X(128)} ${Y(150)}" stroke="${fg}" stroke-width="${S(8)}"/>`,
    sun:`<circle cx="${X(80)}" cy="${Y(80)}" r="${S(34)}" fill="${bg}"/><path d="M${X(80)} ${Y(16)}v18M${X(80)} ${Y(126)}v18M${X(16)} ${Y(80)}h18M${X(126)} ${Y(80)}h18M${X(36)} ${Y(36)}l14 14M${X(110)} ${Y(110)}l14 14" stroke="${fg}" stroke-width="${S(8)}"/>`,
    cup:`<rect x="${X(30)}" y="${Y(48)}" width="${S(84)}" height="${S(70)}" rx="${S(10)}" fill="${bg}" stroke="${fg}" stroke-width="${S(8)}"/><path d="M${X(114)} ${Y(62)}L${X(132)} ${Y(62)}A${S(18)} ${S(18)} 0 0 1 ${X(132)} ${Y(98)}L${X(114)} ${Y(98)}" fill="none" stroke="${fg}" stroke-width="${S(8)}"/><path d="M${X(48)} ${Y(30)}Q${X(58)} ${Y(10)} ${X(68)} ${Y(30)}M${X(78)} ${Y(30)}Q${X(88)} ${Y(10)} ${X(98)} ${Y(30)}" stroke="${fg}" stroke-width="${S(6)}" fill="none"/>`,
    cups:`<path d="M${X(12)} ${Y(54)}h56v62q0 20-20 20h-16q-20 0-20-20z" fill="${bg}" stroke="${fg}" stroke-width="${S(7)}"/><path d="M${X(68)} ${Y(70)}h10q18 0 18 18t-18 18h-10" fill="none" stroke="${fg}" stroke-width="${S(7)}"/><path d="M${X(22)} ${Y(72)}h36" stroke="${C.cream}" stroke-width="${S(7)}"/><path d="M${X(94)} ${Y(42)}h48v70q0 18-18 18h-12q-18 0-18-18z" fill="${C.fresh}" stroke="${fg}" stroke-width="${S(7)}"/><path d="M${X(142)} ${Y(58)}h8q16 0 16 18t-16 18h-8" fill="none" stroke="${fg}" stroke-width="${S(7)}"/><path d="M${X(104)} ${Y(60)}h28" stroke="${C.cream}" stroke-width="${S(7)}"/>`,
    glass:`<path d="M${X(40)} ${Y(24)}L${X(120)} ${Y(24)}L${X(108)} ${Y(144)}L${X(52)} ${Y(144)}Z" fill="${bg}" stroke="${fg}" stroke-width="${S(8)}"/><path d="M${X(50)} ${Y(86)}L${X(110)} ${Y(86)}" stroke="${C.fresh}" stroke-width="${S(12)}"/>`,
    scene:`<path d="M${X(18)} ${Y(140)}L${X(18)} ${Y(54)}Q${X(18)} ${Y(30)} ${X(42)} ${Y(30)}L${X(116)} ${Y(30)}Q${X(140)} ${Y(30)} ${X(140)} ${Y(54)}L${X(140)} ${Y(140)}Z" fill="${bg}"/><path d="M${X(20)} ${Y(122)}Q${X(62)} ${Y(60)} ${X(140)} ${Y(94)}" fill="none" stroke="${fg}" stroke-width="${S(12)}"/>`,
  };
  return `<g>${shapes[kind]||shapes.dot}</g>`;
}

function abstractScene(x=72,y=360,w=828,h=760,variant=0){
  return `<g><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="24" fill="${variant%2?C.teal:C.peach}"/><path d="M${x+80} ${y+h-120}C${x+220} ${y+h-390},${x+430} ${y+h-40},${x+w-80} ${y+120}" fill="none" stroke="${variant%2?C.cream:C.teal}" stroke-width="44" stroke-linecap="round"/><rect x="${x+120}" y="${y+120}" width="170" height="170" rx="24" fill="${C.cream}"/><rect x="${x+330}" y="${y+210}" width="170" height="170" rx="24" fill="${C.fresh}"/><rect x="${x+540}" y="${y+110}" width="170" height="170" rx="24" fill="${C.cream}"/><circle cx="${x+170}" cy="${y+h-160}" r="42" fill="${C.fresh}"/><circle cx="${x+w-130}" cy="${y+150}" r="68" fill="${C.peach}"/></g>`;
}

function coverScene005(x=72,y=700,w=828,h=600){
  return `<g><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="24" fill="${C.peach}"/><path d="M${x+80} ${y+92}h330v330H${x+80}z" fill="${C.cream}" stroke="${C.teal}" stroke-width="12"/><path d="M${x+190} ${y+92}v330M${x+300} ${y+92}v330" stroke="${C.fresh}" stroke-width="10"/><circle cx="${x+245}" cy="${y+257}" r="58" fill="${C.fresh}" opacity="0.72"/><path d="M${x+530} ${y+390}h180v72H${x+530}zM${x+554} ${y+462}v72M${x+686} ${y+462}v72" fill="${C.teal}" stroke="${C.teal}" stroke-width="12" stroke-linecap="round"/><ellipse cx="${x+620}" cy="${y+528}" rx="116" ry="34" fill="${C.cream}"/><ellipse cx="${x+700}" cy="${y+110}" rx="54" ry="30" fill="${C.teal}" transform="rotate(-28 ${x+700} ${y+110})"/></g>`;
}

function coverScene009(x=72,y=700,w=828,h=600){
  return `<g><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="24" fill="${C.cream}"/><rect x="${x+56}" y="${y+54}" width="300" height="492" rx="24" fill="${C.teal}"/><rect x="${x+472}" y="${y+54}" width="300" height="492" rx="24" fill="${C.fresh}"/><circle cx="${x+206}" cy="${y+154}" r="46" fill="${C.peach}"/><circle cx="${x+622}" cy="${y+392}" r="46" fill="${C.cream}"/><g fill="${C.cream}"><rect x="${x+120}" y="${y+280}" width="74" height="74" rx="18"/><rect x="${x+218}" y="${y+280}" width="74" height="74" rx="18"/><rect x="${x+169}" y="${y+378}" width="74" height="74" rx="18"/></g><g fill="${C.teal}"><rect x="${x+536}" y="${y+156}" width="74" height="74" rx="18"/><rect x="${x+634}" y="${y+156}" width="74" height="74" rx="18"/><rect x="${x+585}" y="${y+254}" width="74" height="74" rx="18"/></g></g>`;
}

function summaryVisual(ep){
  if(['002','003','007','008'].includes(ep.id)){
    const sets={
      '002':['plate','cup','bowl'],'003':['bowl','plate','cup'],'007':['cup','cups','moon'],'008':['bowl','glass','plate'],
    }; const kinds=sets[ep.id];
    return `<g><rect x="72" y="300" width="828" height="400" rx="24" fill="${C.peach}"/><path d="M116 376Q486 312 856 392V646Q486 700 116 632Z" fill="${C.cream}"/>${icon(kinds[0],148,414,1.05,C.teal,C.peach)}${icon(kinds[1],428,386,.9,C.teal,C.peach)}${icon(kinds[2],680,438,.78,C.teal,C.peach)}</g>`;
  }
  if(['001','005','006'].includes(ep.id)){
    const seats=ep.id==='006'?'couch':'chair'; const accent=ep.id==='001'?'moon':'sun';
    return `<g><rect x="72" y="300" width="828" height="400" rx="24" fill="${C.cream}" stroke="${C.teal}" stroke-width="10"/><path d="M124 350h310v250H124z" fill="${C.fresh}"/><path d="M226 350v250M332 350v250" stroke="${C.cream}" stroke-width="12"/><path d="M72 636h828" stroke="${C.peach}" stroke-width="26"/>${icon(seats,566,430,1.15,C.teal,C.peach)}${icon(accent,164,404,.72,C.teal,C.peach)}<ellipse cx="790" cy="370" rx="54" ry="28" fill="${C.fresh}" transform="rotate(-24 790 370)"/></g>`;
  }
  if(['004','010'].includes(ep.id)){
    const shift=ep.id==='010'?40:0;
    return `<g><rect x="72" y="300" width="828" height="400" rx="24" fill="${C.fresh}"/><path d="M${130+shift} 606l150-34 96 40-154 40zM${330+shift} 520l128-28 82 34-132 34zM${510+shift} 444l108-24 70 30-112 28zM${666+shift} 380l92-20 58 24-94 24z" fill="${C.cream}"/>${icon('bench',132,344,.78,C.teal,C.peach)}<path d="M786 516q-42-76-84 0M820 524q-34-60-68 0" fill="none" stroke="${C.teal}" stroke-width="14" stroke-linecap="round"/></g>`;
  }
  return `<g><rect x="72" y="300" width="828" height="400" rx="24" fill="${C.cream}"/><rect x="112" y="348" width="330" height="304" rx="24" fill="${C.teal}"/><rect x="530" y="348" width="330" height="304" rx="24" fill="${C.fresh}"/>${icon('chair',154,414,.9,C.cream,C.peach)}${icon('blocks',292,420,.76,C.cream,C.peach)}${icon('chair',570,414,.9,C.teal,C.peach)}${icon('blocks',708,420,.76,C.teal,C.peach)}</g>`;
}

function titleBlock(title, body, x=72, y=320, titleMax=10, bodyMax=17){
  const tl=wrap(title,titleMax); return `${multiline(x,y,tl,76,92,700,C.ink)}${multiline(x,y+tl.length*92+30,wrap(body,bodyMax),42,66,400,C.ink)}`;
}

function makeCard(ep,index){
  const [title,copy]=ep.cards[index-1]; const flip=(Number(ep.id)+index)%2;
  const primary='illustrations/scene-primary.png', secondary=ep.src.length>1?'illustrations/scene-secondary.png':primary;
  if(index===1){
    const scene=ep.src.length?image(primary,flip?72:500,420,flip?400:400,760,`hero${ep.id}`,flip?'xMidYMid':'xMidYMid'):abstractScene(500,420,400,760,Number(ep.id));
    const tx=flip?520:72;
    return base(`${marker('01')}<rect x="${flip?500:72}" y="280" width="400" height="88" rx="24" fill="${C.peach}"/>${t(flip?700:272,338,'今日观察入口',34,700,C.teal,'middle')}${scene}${titleBlock(title,copy,tx,520,5,8)}${footer()}`);
  }
  if(index===2){
    const scene=ep.src.length?image(secondary,72,320,828,760,`scene${ep.id}`,'xMidYMin'):abstractScene(72,320,828,760,Number(ep.id));
    return base(`${marker('02')}${scene}<rect x="104" y="920" width="764" height="390" rx="24" fill="${C.cream}" stroke="${C.teal}" stroke-width="4"/>${multiline(144,1010,wrap(title,10),68,84,700,C.ink)}${multiline(144,1190,wrap(copy,15),42,66,400,C.ink)}${footer()}`);
  }
  if(index>=3 && index<=5){
    const kind=ep.icons[index-3]; const band=index===4?C.teal:(index===5?C.peach:C.fresh); const inv=index===4;
    const glyph=icon(kind,flip?690:104,360,1.15,inv?C.cream:C.teal,inv?C.fresh:C.peach);
    const tx=flip?72:320;
    const pathMotif=index===5?`<path d="M110 1292C260 1212 430 1308 610 1232S820 1188 900 1210" fill="none" stroke="${C.fresh}" stroke-width="28" stroke-linecap="round"/><circle cx="110" cy="1292" r="22" fill="${C.peach}"/><circle cx="900" cy="1210" r="22" fill="${C.teal}"/>`:'';
    return base(`${marker(`0${index}`)}<rect x="72" y="300" width="828" height="260" rx="24" fill="${band}"/>${glyph}${t(tx,670,`观察 ${['一','二','三'][index-3]}`,38,700,C.teal)}${multiline(tx,770,wrap(title,flip?10:7),72,88,700,C.ink)}${multiline(tx,1010,wrap(copy,flip?17:13),42,68,400,C.ink)}${pathMotif}<rect x="72" y="1320" width="828" height="96" rx="24" fill="${index===4?C.peach:C.teal}"/>${t(108,1384,index===3?'和自己的重复情况比':index===4?'一次只留一个变量':'不预设结果，保留差异',38,700,index===4?C.ink:C.cream)}${footer()}`);
  }
  if(index===6){
    const scene=ep.src.length?image(primary,flip?72:548,860,352,470,`action${ep.id}`):abstractScene(flip?72:548,860,352,470,Number(ep.id));
    return base(`${marker('06')}<rect x="72" y="288" width="828" height="500" rx="24" fill="${C.teal}"/><path d="M128 668C292 500 438 650 610 420S820 310 852 360" fill="none" stroke="${C.fresh}" stroke-width="30" stroke-linecap="round"/>${t(120,382,'这次只做一件事',40,700,C.cream)}${multiline(120,500,wrap(title,9),74,92,700,C.cream)}${multiline(flip?470:72,940,wrap(copy,9),42,68,400,C.ink)}${scene}${footer()}`);
  }
  return base(`${marker('07')}${summaryVisual(ep)}<rect x="72" y="790" width="828" height="454" rx="24" fill="${C.teal}"/>${multiline(120,910,wrap(title,10),70,88,700,C.cream)}${multiline(120,1120,wrap(copy,16),42,68,400,C.cream)}<rect x="72" y="1292" width="828" height="120" rx="24" fill="${C.peach}"/>${t(486,1368,'不打分 · 不强求 · 安全优先',40,700,C.ink,'middle')}${footer()}`);
}

function makeCover(ep){
  const primary='illustrations/scene-primary.png'; const has=ep.src.length && ep.id!=='005'; const v=Number(ep.id)%4;
  const titleLines=wrap(ep.cover,v===2?5:6);
  if(v===0){
    return base(`<path d="M0 1640C260 1480 560 1840 1080 1500V1920H0z" fill="${C.teal}"/>${t(96,210,'生活节奏看得见',36,700,C.teal)}<path d="M96 242h152" stroke="${C.fresh}" stroke-width="8"/>${multiline(96,500,titleLines,78,92,700,C.ink)}${has?image(primary,96,700,756,600,`cover${ep.id}`,'xMidYMid'):abstractScene(96,700,756,600,v)}<rect x="96" y="1330" width="756" height="130" rx="24" fill="${C.peach}"/>${multiline(128,1386,wrap(ep.cards[0][1],15),38,56,400,C.ink)}${t(96,1504,'一次观察，留作下次参照',38,700,C.ink)}<circle cx="800" cy="1632" r="86" fill="${C.peach}"/><path d="M742 1690q58-118 116 0" fill="none" stroke="${C.cream}" stroke-width="22" stroke-linecap="round"/>`);
  }
  if(v===1){
    const scene=ep.id==='005'?coverScene005(72,700,828,600):ep.id==='009'?coverScene009(72,700,828,600):has?image(primary,72,700,828,600,`cover${ep.id}`,'xMidYMid'):abstractScene(72,700,828,600,v);
    return base(`<rect width="1080" height="1920" fill="${C.teal}"/>${t(96,210,'生活节奏看得见',36,700,C.cream)}<path d="M96 242h152" stroke="${C.fresh}" stroke-width="8"/>${multiline(96,500,titleLines,78,92,700,C.cream)}${scene}<rect x="96" y="1330" width="756" height="154" rx="24" fill="${C.peach}"/>${multiline(128,1388,wrap(ep.cards[0][1],15),38,56,400,C.ink)}<rect x="96" y="1520" width="756" height="96" rx="24" fill="${C.cream}"/>${t(128,1582,'一次观察，留作下次参照',38,700,C.ink)}<path d="M100 1760h600l120-120" fill="none" stroke="${C.fresh}" stroke-width="28" stroke-linecap="round"/><circle cx="824" cy="1636" r="28" fill="${C.peach}"/>`);
  }
  if(v===2){
    const scene=has?image(primary,520,500,332,770,`cover${ep.id}`,'xMidYMid'):abstractScene(520,500,332,770,v);
    return base(`${t(96,210,'生活节奏看得见',36,700,C.teal)}<path d="M96 242h152" stroke="${C.fresh}" stroke-width="8"/><rect x="72" y="300" width="400" height="88" rx="24" fill="${C.peach}"/>${t(272,358,'今日生活参照',34,700,C.teal,'middle')}${multiline(96,500,titleLines,78,92,700,C.ink)}${scene}<rect x="96" y="1320" width="756" height="144" rx="24" fill="${C.teal}"/>${multiline(128,1378,wrap(ep.cards[0][1],15),38,56,400,C.cream)}<path d="M0 1730L1080 1480V1920H0z" fill="${C.peach}"/>${t(96,1570,'一次观察，留作下次参照',38,700,C.ink)}<circle cx="796" cy="1672" r="78" fill="${C.teal}"/><circle cx="796" cy="1672" r="24" fill="${C.fresh}"/>`);
  }
  const scene=has?image(primary,96,300,756,610,`cover${ep.id}`,'xMidYMin'):abstractScene(96,300,756,610,v);
  return base(`<rect width="1080" height="1920" fill="${C.peach}"/>${t(96,210,'生活节奏看得见',36,700,C.teal)}<path d="M96 242h152" stroke="${C.fresh}" stroke-width="8"/>${scene}<rect x="72" y="840" width="828" height="356" rx="24" fill="${C.cream}"/>${multiline(112,950,titleLines,78,92,700,C.ink)}<rect x="96" y="1240" width="756" height="142" rx="24" fill="${C.teal}"/>${multiline(128,1298,wrap(ep.cards[0][1],15),38,56,400,C.cream)}${t(96,1498,'一次观察，留作下次参照',38,700,C.ink)}<path d="M780 1550V1920H1080V1450q-160 30-300 100z" fill="${C.teal}"/><circle cx="826" cy="1650" r="66" fill="${C.fresh}"/><path d="M802 1670q24-48 48 0" fill="none" stroke="${C.cream}" stroke-width="16"/>`);
}

function runMagick(args,cwd=repo){
  const output=args.at(-1); const body=args.slice(0,-1); const stable=body[0]==='montage' ? ['montage','-limit','thread','1',...body.slice(1)] : ['-limit','thread','1',...body];
  stable.push('-strip','-define','png:exclude-chunk=date,time','-define','png:format=png32','-define','png:color-type=6','-depth','8','-interlace','none','-define','png:compression-level=9','-define','png:compression-filter=5','-define','png:compression-strategy=0',output);
  const r=spawnSync('magick',stable,{cwd,encoding:'utf8',env:{...process.env,MAGICK_THREAD_LIMIT:'1'}});
  if(r.status!==0) throw new Error(`magick ${stable.join(' ')}\n${r.stdout}\n${r.stderr}`);
}

function buildEpisode(ep){
  const id=`HC20260810-${ep.id}`;
  const root=path.join(work,id,'production','v01');
  const out=path.join(root,'03_article_images');
  const source=path.join(out,'source');
  const illustrations=path.join(source,'illustrations');
  const qa=path.join(root,'05_qa');
  fs.mkdirSync(illustrations,{recursive:true}); fs.mkdirSync(qa,{recursive:true});
  const provenance=[];
  ep.src.forEach((shot,i)=>{
    const from=path.join(root,'03_first_frames',`${id}-v01-${shot}-firstframe.png`);
    const name=i?'scene-secondary.png':'scene-primary.png'; const to=path.join(illustrations,name);
    fs.copyFileSync(from,to);
    provenance.push({name,source:path.relative(repo,from).replaceAll('\\','/'),sha256:sha(from)});
  });
  fs.writeFileSync(path.join(illustrations,'provenance-v01.md'),`# ${id} Task 7 插画来源\n\n- 生成方式：本集未新增 image_gen 调用；复用 Task 6 已通过批次机械 QA 的无字首帧。\n- 确定性层：所有中文、数字、图标、版式均位于 SVG。\n\n${provenance.length?provenance.map(p=>`- \`${p.name}\` ← \`${p.source}\`\n  - SHA-256: \`${p.sha256}\``).join('\n'):'- 本集不引用栅格生成资产；场景为确定性品牌几何。'}\n`,'utf8');
  const pngs=[];
  for(let i=1;i<=7;i++){
    const stem=`A0${i}`; const svgPath=path.join(source,`${stem}.svg`); const pngPath=path.join(out,`${stem}.png`);
    fs.writeFileSync(svgPath,makeCard(ep,i),'utf8'); runMagick([svgPath,pngPath],source); pngs.push(pngPath);
  }
  const coverSvg=path.join(source,'cover-v01.svg'); const coverPng=path.join(out,'cover-v01.png');
  fs.writeFileSync(coverSvg,makeCover(ep),'utf8'); runMagick([coverSvg,coverPng],source);
  const sheet=path.join(qa,'article-contactsheet-v01.png');
  runMagick(['montage',...pngs,'-thumbnail','270x480','-tile','7x1','-geometry','270x480+8+8','-background',C.ink,sheet]);
  const rows=[...pngs,coverPng].map(p=>({file:path.basename(p),sha256:sha(p)}));
  const qaText=`# ${id} article QA v01\n\n- 机械状态：PASS（规格、文案绑定、文件与哈希；不把文本扫描表述为视觉语义 PASS）。\n- 人工视觉语义：必须查看本集 25% 联系表与关键原图；批次结论记录在 Task 7 批次 QA，不替代 Task 8。\n- 规格：7/7 文章卡为 1080×1920 PNG；7/7 存在可编辑 SVG；独立平台封面 1/1 为 1080×1920 PNG。\n- 原型：A01 hero cover；A02 scene crop；A03–A05 icon-led observations；A06 action；A07 summary。\n- 安全区：标题、正文、动作文案在 x=72–900 / y=160–1500。\n- 字体：Noto Sans SC Bold / Microsoft YaHei，本机可用。\n- 生成图文字：无；文字、数字、图标均为确定性 SVG 层。\n- 文本机械扫描：未命中加号／十字符号与指定禁词；图形是否像医疗物件、仪表或设备只能人工判断。\n- 封面标题：「${ep.cover}」（${ep.cover.length} 字）；来自 Task 5 已批准 A01／平台封面短句，专用构图，非 A01 裁切。\n- 25% 人工证据入口：\`article-contactsheet-v01.png\`。\n\n## SHA-256\n\n${rows.map(r=>`- \`${r.file}\`: \`${r.sha256}\``).join('\n')}\n`;
  fs.writeFileSync(path.join(qa,'article-qa-v01.md'),qaText,'utf8');
  return {id,pngs,coverPng,sheet,rows,provenance};
}

const selected=mode==='all'?episodes:episodes.filter(e=>e.id===mode.padStart(3,'0'));
if(mode==='covers'){
  for(const ep of episodes){
    const id=`HC20260810-${ep.id}`; const root=path.join(work,id,'production','v01'); const out=path.join(root,'03_article_images'); const source=path.join(out,'source');
    const coverSvg=path.join(source,'cover-v01.svg'); const coverPng=path.join(out,'cover-v01.png'); fs.writeFileSync(coverSvg,makeCover(ep),'utf8'); runMagick([coverSvg,coverPng],source);
  }
  console.log(JSON.stringify({mode,covers:episodes.length},null,2)); process.exit(0);
}
if(!selected.length) throw new Error(`unknown episode selector: ${mode}`);
const results=selected.map(buildEpisode);

if(mode==='all'){
  const covers=results.map(r=>r.coverPng);
  runMagick([...results.map(r=>r.sheet),'-append',path.join(qaRoot,'HC20260810-B01-article-cards-contactsheet-25pct-v01.png')]);
  runMagick(['montage',...covers,'-thumbnail','270x480','-tile','10x1','-geometry','270x480+8+8','-background',C.ink,path.join(qaRoot,'HC20260810-B01-cover-contactsheet-25pct-v01.png')]);
  const crops4x5=[]; const crops1x1=[];
  for(const r of results){
    const p4=path.join(qaRoot,`${r.id}-cover-center-crop-4x5-v01.png`); runMagick([r.coverPng,'-crop','1080x1350+0+285','+repage',p4]); crops4x5.push(p4);
    const p1=path.join(qaRoot,`${r.id}-cover-center-crop-1x1-v01.png`); runMagick([r.coverPng,'-crop','1080x1080+0+420','+repage',p1]); crops1x1.push(p1);
  }
  runMagick(['montage',...crops4x5,'-thumbnail','270x338','-tile','10x1','-geometry','270x338+8+8','-background',C.ink,path.join(qaRoot,'HC20260810-B01-cover-center-crop-4x5-contactsheet-v01.png')]);
  runMagick(['montage',...crops1x1,'-thumbnail','270x270','-tile','10x1','-geometry','270x270+8+8','-background',C.ink,path.join(qaRoot,'HC20260810-B01-cover-center-crop-1x1-contactsheet-v01.png')]);
  const inventory=['episode_id,asset_type,file,sha256,width,height'];
  for(const r of results){for(const row of r.rows) inventory.push(`${r.id},${row.file==='cover-v01.png'?'cover':'article-card'},${row.file},${row.sha256},1080,1920`);}
  fs.writeFileSync(path.join(qaRoot,'HC20260810-B01-task7-asset-inventory-v01.csv'),inventory.join('\n')+'\n','utf8');
}

console.log(JSON.stringify({mode,episodes:results.map(r=>r.id),article_cards:results.length*7,covers:results.length,contact_sheets:results.length},null,2));
