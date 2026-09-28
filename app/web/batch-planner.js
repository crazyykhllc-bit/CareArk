/* Split a local selection into server batches without breaking manual relationships. */
(() => {
  function planUploadBatches(files, groups, encounters, limits, receiving=false){
    const maxSelection=limits.max_selection, maxFiles=limits.max_files_per_batch;
    const maxBatchBytes=limits.max_bytes_per_batch, maxFileBytes=limits.max_bytes_per_file;
    if(files.length>maxSelection)throw new Error(`一次最多选择 ${maxSelection} 个文件；请分次上传`);
    if(!files.length)return [];
    const index=new Map(files.map((file,i)=>[file.key,i]));
    const parent=files.map((_,i)=>i);
    const root=i=>{while(parent[i]!==i){parent[i]=parent[parent[i]];i=parent[i]}return i};
    const join=(a,b)=>{const x=root(a),y=root(b);if(x!==y)parent[y]=x};
    for(const hint of [...groups,...encounters]){
      const selected=(hint.ids||[]).map(id=>index.get(id)).filter(i=>i!==undefined);
      for(let i=1;i<selected.length;i++)join(selected[0],selected[i]);
    }
    const uploaded=files.map((file,i)=>file.uploaded?i:null).filter(i=>i!==null);
    if(receiving)for(let i=1;i<uploaded.length;i++)join(uploaded[0],uploaded[i]);
    const parts=new Map();
    files.forEach((file,i)=>{
      const bytes=Number(file.size??file.file?.size??0);
      if(bytes>maxFileBytes)throw new Error(`${file.name||'文件'}超过单文件大小限制，请移出后重试`);
      const id=root(i);
      if(!parts.has(id))parts.set(id,{indexes:[],bytes:0});
      const part=parts.get(id);part.indexes.push(i);part.bytes+=bytes;
    });
    const components=[...parts.values()].sort((a,b)=>a.indexes[0]-b.indexes[0]);
    for(const part of components){
      if(part.indexes.length>maxFiles)throw new Error(`手动关联的一组超过每批 ${maxFiles} 个文件，请先拆分该组`);
      if(part.bytes>maxBatchBytes)throw new Error('手动关联的一组超过单批大小限制，请先拆分该组');
    }
    if(receiving&&uploaded.length){
      const anchor=components.findIndex(part=>part.indexes.includes(uploaded[0]));
      if(anchor>0)components.unshift(components.splice(anchor,1)[0]);
    }
    const batches=[];let current=[],bytes=0;
    for(const part of components){
      if(current.length&&(current.length+part.indexes.length>maxFiles||bytes+part.bytes>maxBatchBytes)){
        batches.push(current);current=[];bytes=0;
      }
      current.push(...part.indexes.map(i=>files[i].key));bytes+=part.bytes;
    }
    if(current.length)batches.push(current);
    return batches;
  }
  window.planUploadBatches=planUploadBatches;
})();
