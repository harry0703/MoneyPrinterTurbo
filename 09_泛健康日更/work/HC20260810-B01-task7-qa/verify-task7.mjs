import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const repo=process.cwd();
const work=path.join(repo,'09_泛健康日更','work');
const qaRoot=path.join(work,'HC20260810-B01-task7-qa');
const failures=[]; const checks=[]; const inventory=[];
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const expect=(ok,label,detail='')=>{checks.push({label,ok,detail}); if(!ok) failures.push(`${label}${detail?`: ${detail}`:''}`);};
const pngSize=p=>{const b=fs.readFileSync(p); return b.toString('ascii',1,4)==='PNG'?{width:b.readUInt32BE(16),height:b.readUInt32BE(20)}:null;};
const plain=svg=>svg.replace(/<[^>]+>/g,'').replaceAll('&amp;','&').replaceAll('&lt;','<').replaceAll('&gt;','>').replace(/\s+/g,'');

const articleHashes=new Set(); const coverHashes=new Set();
for(let n=1;n<=10;n++){
  const id=`HC20260810-${String(n).padStart(3,'0')}`;
  const root=path.join(work,id,'production','v01');
  const out=path.join(root,'03_article_images'); const source=path.join(out,'source'); const qa=path.join(root,'05_qa');
  const copy=fs.readFileSync(path.join(root,'02_script_storyboard','article-cards-v01.md'),'utf8');
  const titles=[...copy.matchAll(/- 标题：(.+)/g)].map(m=>m[1].trim());
  const bodies=[...copy.matchAll(/- 正文：(.+)/g)].map(m=>m[1].trim());
  expect(titles.length===7 && bodies.length===7,`${id} Task5 copy parse`,`titles=${titles.length}, bodies=${bodies.length}`);
  for(let i=1;i<=7;i++){
    const stem=`A0${i}`; const svgPath=path.join(source,`${stem}.svg`); const pngPath=path.join(out,`${stem}.png`);
    expect(fs.existsSync(svgPath),`${id}/${stem} SVG exists`); expect(fs.existsSync(pngPath),`${id}/${stem} PNG exists`);
    if(!fs.existsSync(svgPath)||!fs.existsSync(pngPath)) continue;
    const svg=fs.readFileSync(svgPath,'utf8'); const text=plain(svg); const dim=pngSize(pngPath); const digest=sha(pngPath);
    expect(svg.includes('width="1080" height="1920"'),`${id}/${stem} SVG canvas`);
    expect(dim?.width===1080 && dim?.height===1920,`${id}/${stem} PNG dimensions`,JSON.stringify(dim));
    expect(text.includes(titles[i-1].replace(/\s+/g,'')),`${id}/${stem} approved title`);
    expect(text.includes(bodies[i-1].replace(/\s+/g,'')),`${id}/${stem} approved body`);
    expect(!/[+\u271a✛✜✠☩☨]/u.test(text),`${id}/${stem} no plus/cross glyph`);
    expect(!/(医疗十字|白大褂|听诊器|处方|证书|认证)/u.test(text),`${id}/${stem} forbidden visible term scan`);
    for(const m of svg.matchAll(/(?:href|xlink:href)="([^"]+)"/g)) expect(m[1].startsWith('illustrations/'),`${id}/${stem} local illustration href`,m[1]);
    articleHashes.add(digest); inventory.push({episode_id:id,asset:stem,sha256:digest,width:dim.width,height:dim.height});
  }
  const coverSvg=path.join(source,'cover-v01.svg'); const coverPng=path.join(out,'cover-v01.png');
  expect(fs.existsSync(coverSvg)&&fs.existsSync(coverPng),`${id} dedicated cover exists`);
  if(fs.existsSync(coverPng)){const dim=pngSize(coverPng); const digest=sha(coverPng); expect(dim?.width===1080&&dim?.height===1920,`${id} cover dimensions`,JSON.stringify(dim)); coverHashes.add(digest); inventory.push({episode_id:id,asset:'cover-v01',sha256:digest,width:dim.width,height:dim.height});}
  expect(fs.existsSync(path.join(qa,'article-contactsheet-v01.png')),`${id} contact sheet exists`);
  expect(fs.existsSync(path.join(qa,'article-qa-v01.md')),`${id} QA markdown exists`);
  expect(fs.existsSync(path.join(source,'illustrations','provenance-v01.md')),`${id} illustration provenance exists`);
}

expect(inventory.filter(x=>x.asset.startsWith('A')).length===70,'70 article PNGs');
expect(inventory.filter(x=>x.asset==='cover-v01').length===10,'10 dedicated covers');
expect(articleHashes.size===70,'70 unique article PNG hashes',`unique=${articleHashes.size}`);
expect(coverHashes.size===10,'10 unique cover hashes',`unique=${coverHashes.size}`);
for(const name of [
  'HC20260810-B01-article-cards-contactsheet-25pct-v01.png',
  'HC20260810-B01-cover-contactsheet-25pct-v01.png',
  'HC20260810-B01-cover-center-crop-4x5-contactsheet-v01.png',
  'HC20260810-B01-cover-center-crop-1x1-contactsheet-v01.png',
]) expect(fs.existsSync(path.join(qaRoot,name)),`${name} exists`);

const report={status:failures.length?'FAIL':'PASS',generated_at:'2026-08-15T10:30:00+08:00',summary:{checks:checks.length,passed:checks.filter(x=>x.ok).length,failed:failures.length,article_pngs:70,covers:10,unique_article_hashes:articleHashes.size,unique_cover_hashes:coverHashes.size},failures,checks,inventory};
fs.writeFileSync(path.join(qaRoot,'HC20260810-B01-task7-mechanical-qa-v01.json'),JSON.stringify(report,null,2)+'\n','utf8');
console.log(JSON.stringify(report.summary,null,2));
if(failures.length){for(const f of failures) console.error(f); process.exit(1);}
