import io,json,base64
from PIL import Image
from creatorlab import materials


def test_multimodal_call_sends_only_selected_images_and_distinguishes_hypotheses(monkeypatch):
    im=io.BytesIO();Image.new('RGB',(100,120),'blue').save(im,format='PNG')
    captured={}
    def post(url,payload,headers=None,timeout=None):
        captured['payload']=payload
        answer={'observed':['图中有蓝色背景'],'hypotheses':['更明确的主体也许值得测试'],'next_test':'仅替换封面主体','limits':['没有完整视频']}
        return {'choices':[{'message':{'content':json.dumps(answer)}}]}
    monkeypatch.setattr(materials,'_post',post)
    result=materials.analyze('openai','vision-test','secret','标题','实际字幕',[('用户确认的封面',materials.image_bytes(im.getvalue()))])
    parts=captured['payload']['messages'][1]['content']
    assert len(parts)==2 and parts[1]['type']=='image_url'
    assert base64.b64decode(parts[1]['image_url']['url'].split(',')[1]).startswith(b'\xff\xd8')
    assert result['scope']==['用户确认的封面'] and len(result['evidence_hashes'])==1
    assert 'secret' not in json.dumps(result)
