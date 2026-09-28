(() => {
  const select=document.getElementById('profileSwitcher');
  const dialog=document.getElementById('profileCreateDialog');
  const form=document.getElementById('profileCreateForm');
  const nameInput=document.getElementById('profileCreateName');
  const error=document.getElementById('profileCreateError');

  window.loadProfiles=async()=>{
    const result=await api.get('/api/profiles');
    const profiles=result.items?.length?result.items:[{id:state.user.id,name:'我',is_self:true}];
    const active=profiles.find(item=>item.id===(result.active_id||state.user.id));
    if(!active)throw new Error('当前档案成员不可用，请重新登录');
    state.activeProfileId=active.id;
    state.activeProfileName=active.name;
    select.replaceChildren(...profiles.map(item=>new Option(item.is_self?'我':item.name,item.id)),
      new Option('＋ 新增成员…','__add__'));
    select.value=active.id;
    document.getElementById('uploadProfileName').textContent=active.name;
  };

  select.addEventListener('change',async()=>{
    const id=select.value;
    if(id==='__add__'){
      select.value=state.activeProfileId;
      form.reset();error.textContent='';dialog.showModal();nameInput.focus();
      return;
    }
    if(id===state.activeProfileId)return;
    select.disabled=true;
    try{
      await api.post('/api/profiles/active',{profile_id:id});
      location.reload();
    }catch(cause){
      select.disabled=false;select.value=state.activeProfileId;toast(errorText(cause));
    }
  });

  const close=()=>dialog.close();
  document.getElementById('profileCreateClose').addEventListener('click',close);
  document.getElementById('profileCreateCancel').addEventListener('click',close);
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    const button=form.querySelector('[type="submit"]');button.disabled=true;error.textContent='';
    try{
      const profile=await api.post('/api/profiles',{name:nameInput.value.trim()});
      await api.post('/api/profiles/active',{profile_id:profile.id});
      location.reload();
    }catch(cause){error.textContent=errorText(cause);button.disabled=false}
  });
})();
