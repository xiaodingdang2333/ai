const CDP = require('chrome-remote-interface');

(async () => {
  const client = await CDP({ port: 9223 });
  const { Runtime } = client;
  const result = await Runtime.evaluate({
    expression: `({
      inputs: [...document.querySelectorAll('input,textarea,[contenteditable=true],[role=textbox]')].map((el,i)=>{
        const r=el.getBoundingClientRect();
        return {i, tag:el.tagName, type:el.type||'', placeholder:el.placeholder||'', text:(el.innerText||el.value||'').slice(0,80), cls:String(el.className||'').slice(0,100), x:r.x,y:r.y,w:r.width,h:r.height};
      }),
      buttons: [...document.querySelectorAll('button,a,div,span')].map((el,i)=>{
        const r=el.getBoundingClientRect();
        return {i, tag:el.tagName, text:(el.innerText||el.textContent||'').trim().replace(/\\s+/g,' ').slice(0,80), cls:String(el.className||'').slice(0,80), x:r.x,y:r.y,w:r.width,h:r.height};
      }).filter(x=>x.text && x.w>0 && x.h>0).slice(0,200)
    })`,
    returnByValue: true
  });
  console.log(JSON.stringify(result.result.value, null, 2));
  await client.close();
})();
