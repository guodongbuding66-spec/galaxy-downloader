// Acceptance screenshots of the running app in a separate CI test browser.
const { chromium }=require(process.env.GALAXY_PLAYWRIGHT_MODULE||'@playwright/test');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
let activeBrowser;
(async()=>{
 const out=path.resolve(process.env.GALAXY_EVIDENCE_DIR||'qa');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true});activeBrowser=browser;
 const page=await browser.newPage({viewport:{width:1440,height:1050},deviceScaleFactor:1});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:3010/zh',{waitUntil:'domcontentloaded',timeout:90000});
 await page.getByRole('button',{name:'解析链接',exact:true}).waitFor({timeout:90000});
 await page.screenshot({path:path.join(out,'web-workbench-desktop.png')});
 assert.equal(await page.locator('#url').count(),1);
 await page.getByRole('button',{name:'批量下载',exact:true}).click();
 await page.screenshot({path:path.join(out,'web-workbench-batch.png')});
 const mobile=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
 await mobile.goto('http://127.0.0.1:3010/zh',{waitUntil:'domcontentloaded',timeout:90000});
 await mobile.getByRole('button',{name:'解析链接',exact:true}).waitFor({timeout:90000});
 assert.ok(await mobile.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1),'mobile horizontal overflow');
 await mobile.screenshot({path:path.join(out,'web-workbench-mobile.png'),fullPage:true});
 fs.writeFileSync(path.join(out,'web-runtime.json'),JSON.stringify({desktop:true,batch:true,mobile:true,horizontalOverflow:false,pageErrors:errors,mock:false},null,2));
 assert.deepEqual(errors,[]);await browser.close();
})().catch(async error=>{console.error(error);if(activeBrowser)await activeBrowser.close();process.exit(1)});
