import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawnSync} from 'node:child_process';

const repo=process.cwd();
const work=path.join(repo,'09_泛健康日更','work');
const qaRoot=path.join(work,'HC20260810-B01-task7-qa');
const failures=[]; const checks=[]; const inventory=[]; const geometryWarnings=[];
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const expect=(ok,label,detail='')=>{checks.push({label,ok,detail}); if(!ok) failures.push(`${label}${detail?`: ${detail}`:''}`);};
const pngSize=p=>{const b=fs.readFileSync(p); return b.toString('ascii',1,4)==='PNG'?{width:b.readUInt32BE(16),height:b.readUInt32BE(20)}:null;};
const plain=svg=>svg.replace(/<[^>]+>/g,'').replaceAll('&amp;','&').replaceAll('&lt;','<').replaceAll('&gt;','>').replace(/\s+/g,'');
const listFiles=dir=>fs.existsSync(dir)?fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?listFiles(path.join(dir,e.name)):path.join(dir,e.name)):[];
const rel=(root,p)=>path.relative(root,p).replaceAll('\\','/');

function pngChunkTypes(p){
  const b=fs.readFileSync(p); const types=[]; let at=8;
  while(at+12<=b.length){const len=b.readUInt32BE(at); const type=b.toString('ascii',at+4,at+8); types.push(type); at+=12+len; if(type==='IEND') break;}
  return types;
}

function geometry(svg,sourceDir){
  return svg.replace(/<text\b[^>]*>[\s\S]*?<\/text>/g,'')
    .replace(/(href|xlink:href)="illustrations\/([^"]+)"/g,(full,attr,name)=>{const p=path.join(sourceDir,'illustrations',name); return `${attr}="RASTER:${fs.existsSync(p)?sha(p):'MISSING'}"`;})
    .replace(/(cover|hero|scene|action)\d{3}/g,'$1XXX').replace(/\s+/g,' ').trim();
}

function approvedCoverTitles(root){
  const article=fs.readFileSync(path.join(root,'02_script_storyboard','article-cards-v01.md'),'utf8');
  const platform=fs.readFileSync(path.join(root,'02_script_storyboard','platform-copy-v01.md'),'utf8');
  const first=(article.match(/- 标题：(.+)/)||[])[1]?.trim(); const values=[];
  if(first) values.push(first);
  for(const block of platform.matchAll(/### 封面短句（2条）\s*\n([\s\S]*?)(?=\n### |\n## |$)/g)){
    for(const line of block[1].matchAll(/^\d+\.\s*(.+)$/gm)) values.push(line[1].trim());
  }
  return [...new Set(values)];
}

function generatedPaths(root,includeMechanical=true){
  const paths=[];
  for(let n=1;n<=10;n++){
    const id=`HC20260810-${String(n).padStart(3,'0')}`; const base=path.join(root,'09_泛健康日更','work',id,'production','v01');
    paths.push(...listFiles(path.join(base,'03_article_images')));
    for(const name of ['article-contactsheet-v01.png','article-qa-v01.md']) paths.push(path.join(base,'05_qa',name));
  }
  const q=path.join(root,'09_泛健康日更','work','HC20260810-B01-task7-qa');
  paths.push(...listFiles(q).filter(p=>{
    const n=path.basename(p);
    return /cover-center-crop-(?:1x1|4x5)-v01\.png$/.test(n)||[
      'HC20260810-B01-article-cards-contactsheet-25pct-v01.png','HC20260810-B01-cover-contactsheet-25pct-v01.png',
      'HC20260810-B01-cover-center-crop-4x5-contactsheet-v01.png','HC20260810-B01-cover-center-crop-1x1-contactsheet-v01.png',
      'HC20260810-B01-task7-asset-inventory-v01.csv',
      ...(includeMechanical?['HC20260810-B01-task7-mechanical-qa-v01.json']:[]),
    ].includes(n);
  }));
  return paths.filter(fs.existsSync).sort((a,b)=>rel(root,a).localeCompare(rel(root,b),'en'));
}

function requiredReproPath(relative){
  return /\/03_article_images\/(?:A0[1-7]|cover-v01)\.png$/.test(relative)
    || /\/05_qa\/article-(?:contactsheet-v01\.png|qa-v01\.md)$/.test(relative)
    || /HC20260810-B01-task7-qa\/HC20260810-\d{3}-cover-center-crop-(?:1x1|4x5)-v01\.png$/.test(relative)
    || /HC20260810-B01-task7-qa\/HC20260810-B01-.*contactsheet.*\.png$/.test(relative)
    || relative.endsWith('/HC20260810-B01-task7-asset-inventory-v01.csv')
    || relative.endsWith('/HC20260810-B01-task7-mechanical-qa-v01.json');
}

function inputPaths(root){
  const paths=[];
  for(let n=1;n<=10;n++){
    const id=`HC20260810-${String(n).padStart(3,'0')}`; const base=path.join(root,'09_泛健康日更','work',id,'production','v01');
    paths.push(path.join(base,'02_script_storyboard','article-cards-v01.md'),path.join(base,'02_script_storyboard','platform-copy-v01.md'));
    const provenance=path.join(base,'03_article_images','source','illustrations','provenance-v01.md');
    if(fs.existsSync(provenance)){
      const text=fs.readFileSync(provenance,'utf8');
      for(const m of text.matchAll(/← `([^`]+)`/g)) paths.push(path.join(root,...m[1].split('/')));
    }
  }
  paths.push(path.join(root,'09_泛健康日更','branding','生活节奏看得见','brand-lock-v01.md'));
  const q=path.join(root,'09_泛健康日更','work','HC20260810-B01-task7-qa');
  paths.push(path.join(q,'build-task7-article-cards.mjs'),path.join(q,'verify-task7.mjs'));
  return [...new Set(paths)].filter(fs.existsSync).sort((a,b)=>rel(root,a).localeCompare(rel(root,b),'en'));
}

function writeDoubleBuildEvidence(rootA,rootB){
  const filesA=generatedPaths(rootA,true), filesB=generatedPaths(rootB,true);
  const mapA=new Map(filesA.map(p=>[rel(rootA,p),{bytes:fs.statSync(p).size,sha256:sha(p)}]));
  const mapB=new Map(filesB.map(p=>[rel(rootB,p),{bytes:fs.statSync(p).size,sha256:sha(p)}]));
  const names=[...new Set([...mapA.keys(),...mapB.keys()])].sort(); const mismatches=[];
  for(const name of names){const a=mapA.get(name),b=mapB.get(name); if(!a||!b||a.bytes!==b.bytes||a.sha256!==b.sha256)mismatches.push({file:name,build_a:a||null,build_b:b||null});}
  const inputsA=inputPaths(rootA),inputsB=inputPaths(rootB); const inA=new Map(inputsA.map(p=>[rel(rootA,p),sha(p)])),inB=new Map(inputsB.map(p=>[rel(rootB,p),sha(p)]));
  const inputNames=[...new Set([...inA.keys(),...inB.keys()])].sort(); const inputMismatches=inputNames.filter(n=>inA.get(n)!==inB.get(n));
  const fontFiles=['C:/Windows/Fonts/Noto Sans SC Bold (TrueType).otf','C:/Windows/Fonts/msyh.ttc'];
  const magick=spawnSync('magick',['-version'],{encoding:'utf8'});
  const manifest=Object.fromEntries(names.map(n=>[n,mapA.get(n)||null]));
  const evidence={
    status:mismatches.length||inputMismatches.length?'FAIL':'PASS',schema:'task7-double-build-v01',
    builds:['isolated-build-a','isolated-build-b'],files_compared:names.length,required_files_compared:names.filter(requiredReproPath).length,
    path_sets_equal:filesA.length===filesB.length&&filesA.length===names.length,all_byte_sha_equal:mismatches.length===0,mismatches,
    input_files_compared:inputNames.length,input_manifests_equal:inputMismatches.length===0,input_mismatches:inputMismatches,
    runtime:{node:process.version,magick_version:(magick.stdout||magick.stderr||'').trim(),magick_thread_limit:1,
      fonts:Object.fromEntries(fontFiles.map(p=>[p,{exists:fs.existsSync(p),sha256:fs.existsSync(p)?sha(p):null}]))},
    output_manifest:manifest,
  };
  fs.writeFileSync(path.join(qaRoot,'HC20260810-B01-task7-reproducibility-v01.json'),JSON.stringify(evidence,null,2)+'\n','utf8');
  console.log(JSON.stringify({status:evidence.status,files_compared:evidence.files_compared,required_files_compared:evidence.required_files_compared,mismatches:mismatches.length,input_mismatches:inputMismatches.length},null,2));
  if(evidence.status!=='PASS') process.exit(1);
}

const compareAt=process.argv.indexOf('--compare-builds');
if(compareAt>=0){
  const a=process.argv[compareAt+1],b=process.argv[compareAt+2];
  if(!a||!b) throw new Error('usage: verify-task7.mjs --compare-builds ROOT_A ROOT_B');
  writeDoubleBuildEvidence(path.resolve(a),path.resolve(b)); process.exit(0);
}

const articleHashes=new Set(); const coverHashes=new Set(); const coverGeometry=[]; const a07Geometry=[]; let provenanceEntries=0;
const generatedPngs=[];
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
    expect(!/(医疗十字|白大褂|听诊器|处方|证书|认证)/u.test(text),`${id}/${stem} forbidden visible term text scan`);
    for(const m of svg.matchAll(/(?:href|xlink:href)="([^"]+)"/g)) expect(m[1].startsWith('illustrations/'),`${id}/${stem} local illustration href`,m[1]);
    if(i===7)a07Geometry.push({id,sha256:crypto.createHash('sha256').update(geometry(svg,source)).digest('hex')});
    articleHashes.add(digest); inventory.push({episode_id:id,asset:stem,sha256:digest,width:dim.width,height:dim.height}); generatedPngs.push(pngPath);
  }
  const coverSvg=path.join(source,'cover-v01.svg'); const coverPng=path.join(out,'cover-v01.png');
  expect(fs.existsSync(coverSvg)&&fs.existsSync(coverPng),`${id} dedicated cover exists`);
  if(fs.existsSync(coverSvg)){
    const svg=fs.readFileSync(coverSvg,'utf8'); const match=svg.match(/<text\b[^>]*font-size="78"[^>]*>([\s\S]*?)<\/text>/); const coverTitle=match?plain(match[1]):'';
    const approved=approvedCoverTitles(root); expect(svg.includes('width="1080" height="1920"'),`${id} cover SVG canvas`);
    expect(approved.includes(coverTitle),`${id} cover title bound to Task5`,`title=${coverTitle}`);
    expect(Array.from(coverTitle).length>=8&&Array.from(coverTitle).length<=12,`${id} cover title 8-12 characters`,`title=${coverTitle}, length=${Array.from(coverTitle).length}`);
    coverGeometry.push({id,sha256:crypto.createHash('sha256').update(geometry(svg,source)).digest('hex')});
  }
  if(fs.existsSync(coverPng)){const dim=pngSize(coverPng); const digest=sha(coverPng); expect(dim?.width===1080&&dim?.height===1920,`${id} cover dimensions`,JSON.stringify(dim)); coverHashes.add(digest); inventory.push({episode_id:id,asset:'cover-v01',sha256:digest,width:dim.width,height:dim.height}); generatedPngs.push(coverPng);}
  const sheet=path.join(qa,'article-contactsheet-v01.png'); expect(fs.existsSync(sheet),`${id} contact sheet exists`); if(fs.existsSync(sheet))generatedPngs.push(sheet);
  expect(fs.existsSync(path.join(qa,'article-qa-v01.md')),`${id} QA markdown exists`);
  const illDir=path.join(source,'illustrations'); const provenance=path.join(illDir,'provenance-v01.md'); expect(fs.existsSync(provenance),`${id} illustration provenance exists`);
  if(fs.existsSync(provenance)){
    const text=fs.readFileSync(provenance,'utf8'); const entries=[...text.matchAll(/- `([^`]+)` ← `([^`]+)`\s*\n\s*- SHA-256: `([a-f0-9]{64})`/g)];
    const localPngs=listFiles(illDir).filter(p=>p.toLowerCase().endsWith('.png'));
    expect(entries.length===localPngs.length,`${id} provenance entry count`,`declared=${entries.length}, local_pngs=${localPngs.length}`);
    for(const m of entries){
      const local=path.join(illDir,m[1]),origin=path.join(repo,...m[2].split('/')); provenanceEntries++;
      expect(fs.existsSync(local)&&fs.existsSync(origin),`${id} provenance source/copy exists`,`${m[1]} <- ${m[2]}`);
      if(fs.existsSync(local)&&fs.existsSync(origin)){
        const localSha=sha(local),sourceSha=sha(origin); expect(localSha===sourceSha&&sourceSha===m[3],`${id} provenance source/copy SHA`,`declared=${m[3]}, source=${sourceSha}, copy=${localSha}`);
      }
    }
  }
}

expect(provenanceEntries===17,'17 provenance source/copy bindings',`entries=${provenanceEntries}`);
expect(inventory.filter(x=>x.asset.startsWith('A')).length===70,'70 article PNGs');
expect(inventory.filter(x=>x.asset==='cover-v01').length===10,'10 dedicated covers');
expect(articleHashes.size===70,'70 unique article PNG hashes',`unique=${articleHashes.size}`);
expect(coverHashes.size===10,'10 unique cover hashes',`unique=${coverHashes.size}`);
const a07Unique=new Set(a07Geometry.map(x=>x.sha256)); expect(a07Unique.size>=4,'A07 at least four text-free geometry fingerprints',`unique=${a07Unique.size}`);
const c005=coverGeometry.find(x=>x.id.endsWith('005')),c009=coverGeometry.find(x=>x.id.endsWith('009')); expect(c005?.sha256!==c009?.sha256,'005/009 cover text-free geometry differs');
for(const [kind,items] of [['A07',a07Geometry],['cover',coverGeometry]]){
  const groups=Map.groupBy(items,x=>x.sha256); for(const group of groups.values()) if(group.length>1) geometryWarnings.push({kind,episodes:group.map(x=>x.id),message:'去文案几何完全同构；需人工确认是否有足够的主题图像差异'});
}

for(const name of [
  'HC20260810-B01-article-cards-contactsheet-25pct-v01.png','HC20260810-B01-cover-contactsheet-25pct-v01.png',
  'HC20260810-B01-cover-center-crop-4x5-contactsheet-v01.png','HC20260810-B01-cover-center-crop-1x1-contactsheet-v01.png',
]){const p=path.join(qaRoot,name); expect(fs.existsSync(p),`${name} exists`); if(fs.existsSync(p))generatedPngs.push(p);}
for(let n=1;n<=10;n++)for(const aspect of ['1x1','4x5']){const p=path.join(qaRoot,`HC20260810-${String(n).padStart(3,'0')}-cover-center-crop-${aspect}-v01.png`);expect(fs.existsSync(p),`${path.basename(p)} exists`);if(fs.existsSync(p))generatedPngs.push(p);}

const forbiddenChunks=new Set(['tEXt','zTXt','iTXt','tIME','eXIf']);
for(const p of generatedPngs){const bad=pngChunkTypes(p).filter(x=>forbiddenChunks.has(x)); expect(bad.length===0,`${rel(repo,p)} deterministic PNG chunks`,`forbidden=${bad.join(',')}`);}

const csvPath=path.join(qaRoot,'HC20260810-B01-task7-asset-inventory-v01.csv'); expect(fs.existsSync(csvPath),'asset inventory exists');
if(fs.existsSync(csvPath)){
  const rows=fs.readFileSync(csvPath,'utf8').trim().split(/\r?\n/).slice(1).map(line=>line.split(',')); expect(rows.length===80,'asset inventory has 80 rows',`rows=${rows.length}`);
  for(const [episode,type,file,digest,width,height] of rows){const p=path.join(work,episode,'production','v01','03_article_images',file); expect(fs.existsSync(p)&&sha(p)===digest&&width==='1080'&&height==='1920',`${episode}/${file} inventory byte SHA and dimensions`);}
}

const skipRepro=process.argv.includes('--skip-repro-evidence'); const reproPath=path.join(qaRoot,'HC20260810-B01-task7-reproducibility-v01.json');
if(!skipRepro){
  expect(fs.existsSync(reproPath),'double-build reproducibility evidence exists');
  if(fs.existsSync(reproPath)){const r=JSON.parse(fs.readFileSync(reproPath,'utf8')); expect(r.status==='PASS'&&r.path_sets_equal&&r.all_byte_sha_equal&&r.mismatches.length===0,'double-build all generated bytes match',`files=${r.files_compared}, mismatches=${r.mismatches.length}`); expect(r.files_compared===233&&r.required_files_compared===126,'double-build coverage includes 233 generated / 126 required files',`files=${r.files_compared}, required=${r.required_files_compared}`); expect(r.input_manifests_equal&&r.input_mismatches.length===0,'double-build inputs match',`inputs=${r.input_files_compared}`);}
}

const report={status:failures.length?'FAIL':'PASS',schema:'task7-mechanical-qa-v02',summary:{checks:checks.length,passed:checks.filter(x=>x.ok).length,failed:failures.length,article_pngs:70,covers:10,unique_article_hashes:articleHashes.size,unique_cover_hashes:coverHashes.size,a07_unique_text_free_geometries:a07Unique.size,geometry_clone_warnings:geometryWarnings.length,repro_evidence_checked:!skipRepro},failures,geometry_clone_warnings:geometryWarnings,manual_visual_review_required:['图标或场景是否像医疗物件、药片、设备、数据图表或仪表','缩略图第一语义与文章主题是否一致','人物与物件裁切、平台安全区与真实平台适配'],checks,inventory};
fs.writeFileSync(path.join(qaRoot,'HC20260810-B01-task7-mechanical-qa-v01.json'),JSON.stringify(report,null,2)+'\n','utf8');
console.log(JSON.stringify(report.summary,null,2));
if(failures.length){for(const f of failures) console.error(f); process.exit(1);}
