import test from 'node:test';
import assert from 'node:assert/strict';
import {EXPERTS,isLocalExpertHost,outputURL} from '../advanced-ui.mjs';
import {advancedKeys,advancedMessages,advancedText} from '../advanced-i18n.mjs';
import {languages} from '../i18n.mjs';

test('exact expert catalog separates text, images and video',()=>{
 assert.equal(EXPERTS.length,7);assert.equal(new Set(EXPERTS.map(e=>e.id)).size,7);
 assert.equal(EXPERTS.find(e=>e.id==='qwen-text').kind,'text');
 assert.equal(EXPERTS.find(e=>e.id==='liveportrait').kind,'video');
 assert.equal(EXPERTS.find(e=>e.id==='multidiffusion').kind,'image');
});
test('local expert service never probes Pages or file origins',()=>{
 for(const value of ['https://kuonanhong.github.io/Frame_to_Video/','file:///tmp/index.html','http://evil.test/','http://localhost.attacker.test/','http://192.168.1.2/'])assert.equal(isLocalExpertHost(new URL(value)),false,value);
 for(const value of ['http://localhost:8787/','http://127.0.0.1:8787/','http://[::1]:8787/'])assert.equal(isLocalExpertHost(new URL(value)),true,value);
});
test('expert result URLs cannot read arbitrary hosts or other jobs',()=>{
 const base='http://127.0.0.1:8787/';
 assert.equal(outputURL('/api/experts/jobs/abc/result.png',base,'abc'),base+'api/experts/jobs/abc/result.png');
 for(const value of ['https://evil.test/api/experts/jobs/abc/result.png','/api/experts/jobs/other/result.png','/secret','/api/experts/jobs/abc/../../secret'])assert.throws(()=>outputURL(value,base,'abc'));
});
test('all editor locales explicitly translate the new expert controls',()=>{
 for(const {code} of languages){assert.equal(advancedMessages[code]?.length,advancedKeys.length,code);for(const key of advancedKeys)assert.ok(advancedText(key,code).trim(),`${code}:${key}`)}
});
