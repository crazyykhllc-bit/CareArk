const {defineConfig}=require('@playwright/test');
module.exports=defineConfig({testDir:'./tests/browser',timeout:20000,use:{channel:'chrome',headless:true,viewport:{width:1440,height:1000}},reporter:'list'});
