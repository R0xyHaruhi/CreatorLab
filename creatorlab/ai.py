"""Optional AI providers. Core analytics works without keys or model downloads."""
import json
import os
from urllib import request, error

SYSTEM = ('You are a careful creator analytics assistant. Use only the supplied data. '
          'Separate observed evidence from hypotheses, acknowledge small samples, '
          'never promise virality, and provide a concrete next experiment. '
          'Respond in the same language as the user request.')

TEXT_PROVIDERS={
    'deepseek':dict(url='https://api.deepseek.com/chat/completions',key='DEEPSEEK_API_KEY',
                    model_env='DEEPSEEK_MODEL',model='deepseek-flash'),
    'doubao':dict(url='https://ark.cn-beijing.volces.com/api/v3/chat/completions',key='ARK_API_KEY',
                  model_env='DOUBAO_MODEL',model='doubao-seed-2-1-lite-260915'),
}

class AIError(RuntimeError):
    pass

def _post(url, payload, headers=None, timeout=45):
    body = json.dumps(payload).encode('utf-8')
    req = request.Request(url, data=body, headers={'Content-Type':'application/json', **(headers or {})}, method='POST')
    try:
        with request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read().decode('utf-8'))
    except error.HTTPError as exc:
        raise AIError(f'模型请求失败（HTTP {exc.code}），请核对模型权限、余额与限流状态。') from None
    except (error.URLError, TimeoutError, ValueError):
        raise AIError('模型请求未完成，请检查网络或稍后重试；本地分析仍可使用。') from None

def generate(provider, prompt, context, model=None, ollama_url=None, api_key=None):
    """Provider choices: none, ollama, openai. No silent fallback to cloud."""
    if provider == 'none':
        return ('Local analytics mode: no language model was called. Review the evidence and '
                'experiment proposal in the dashboard. Select Ollama or OpenAI for a narrative.')
    messages = [{'role':'system','content':SYSTEM}, {'role':'user','content':f'Creator data (JSON):\n{json.dumps(context, ensure_ascii=False)}\n\nTask:\n{prompt}'}]
    if provider in TEXT_PROVIDERS:
        config=TEXT_PROVIDERS[provider]
        key=api_key or os.getenv(config['key'])
        if not key:raise AIError('请配置 '+config['key']+'，或在当前会话输入API Key')
        data=_post(config['url'],{'model':model or os.getenv(config['model_env']) or config['model'],
                   'messages':messages,'stream':False,'thinking':{'type':'disabled'}},
                   {'Authorization':'Bearer '+key},timeout=60)
        try:
            text=data['choices'][0]['message']['content']
            if not isinstance(text,str) or not text.strip():raise ValueError()
            return text
        except (KeyError,IndexError,TypeError,ValueError):
            raise AIError('模型未返回可用正文，请核对模型名称和服务状态。') from None
    if provider == 'ollama':
        base = (ollama_url or os.getenv('OLLAMA_BASE_URL','http://localhost:11434')).rstrip('/')
        if not (base.startswith('http://localhost:') or base.startswith('http://127.0.0.1:')):
            raise AIError('Ollama URL must be a local loopback address in this MVP.')
        data = _post(base+'/api/chat', {'model':model or os.getenv('OLLAMA_MODEL','qwen2.5:3b'), 'messages':messages, 'stream':False})
        return data['message']['content']
    if provider == 'openai':
        key = api_key or os.getenv('OPENAI_API_KEY')
        if not key:
            raise AIError('OPENAI_API_KEY is missing. Set it locally; never commit it to GitHub.')
        data = _post('https://api.openai.com/v1/chat/completions', {'model':model or os.getenv('OPENAI_MODEL','gpt-4.1-mini'), 'messages':messages}, {'Authorization':f'Bearer {key}'})
        return data['choices'][0]['message']['content']
    raise AIError('Unknown provider')
