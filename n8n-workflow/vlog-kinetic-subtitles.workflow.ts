import {
  workflow,
  node,
  trigger,
  merge,
  newCredential,
  expr,
} from '@n8n/workflow-sdk';

const webhookTrigger = trigger({
  type: 'n8n-nodes-base.webhook',
  version: 2.1,
  config: {
    name: 'Vlog Upload Webhook',
    position: [0, 0],
    parameters: {
      httpMethod: 'POST',
      path: 'vlog-kinetic-subtitles',
      responseMode: 'responseNode',
      options: {
        binaryData: true,
        binaryPropertyName: 'video',
      },
    },
  },
  output: [
    {
      headers: {},
      params: {},
      query: {},
      body: { topic: 'A weekend trip to the mountains', voiceId: '21m00Tcm4TlvDq8ikWAM' },
      webhookUrl: 'https://your-n8n-host/webhook/vlog-kinetic-subtitles',
      executionMode: 'production',
    },
  ],
});

const normalizeInput = node({
  type: 'n8n-nodes-base.set',
  version: 3.4,
  config: {
    name: 'Normalize Input',
    position: [260, 0],
    parameters: {
      mode: 'manual',
      includeOtherFields: true,
      assignments: {
        assignments: [
          {
            id: 'topic',
            name: 'topic',
            value: expr('{{ $json.body?.topic ?? $json.topic ?? "Todays vlog" }}'),
            type: 'string',
          },
          {
            id: 'voiceId',
            name: 'voiceId',
            value: expr('{{ $json.body?.voiceId ?? $json.voiceId ?? "21m00Tcm4TlvDq8ikWAM" }}'),
            type: 'string',
          },
          {
            id: 'scriptPath',
            name: 'scriptPath',
            value: '/data/scripts/burn_kinetic_subtitles.py',
            type: 'string',
          },
        ],
      },
      options: {
        includeBinary: true,
      },
    },
  },
  output: [
    {
      topic: 'A weekend trip to the mountains',
      voiceId: '21m00Tcm4TlvDq8ikWAM',
      scriptPath: '/data/scripts/burn_kinetic_subtitles.py',
    },
  ],
});

const generateScript = node({
  type: '@n8n/n8n-nodes-langchain.openAi',
  version: 2.3,
  config: {
    name: 'Generate Script',
    position: [520, 0],
    parameters: {
      resource: 'text',
      operation: 'response',
      modelId: { __rl: true, mode: 'id', value: 'gpt-5.4' },
      responses: {
        values: [
          {
            type: 'text',
            role: 'system',
            content:
              'You write short, punchy vertical-vlog narration scripts, ' +
              'about 60 to 90 words (18 to 30 seconds when read aloud). ' +
              'Style: confident, editorial, energetic, second person, short sentences. ' +
              'No hashtags, no emojis, no titles, no quotation marks around the whole script. ' +
              'Wrap exactly 3 to 5 of the most important words or short phrases in double ' +
              'asterisks, for example **like this**, to mark them as kinetic emphasis keywords. ' +
              'Output only the narration script text, nothing else.',
          },
          {
            type: 'text',
            role: 'user',
            content: expr(
              'Topic or notes for this vlog: {{ $json.topic }}\n\nWrite the narration script now.'
            ),
          },
        ],
      },
      options: {
        temperature: 0.9,
        maxTokens: 400,
      },
    },
    credentials: {
      openAiApi: newCredential('OpenAI account'),
    },
  },
  output: [
    {
      content:
        'Every great **idea** starts with one bold **question**. Keep the message clear ' +
        'and always moving, because small words build big moments.',
    },
  ],
});

const cleanScriptText = node({
  type: 'n8n-nodes-base.code',
  version: 2,
  config: {
    name: 'Clean Script Text',
    position: [780, 0],
    parameters: {
      mode: 'runOnceForAllItems',
      language: 'javaScript',
      jsCode:
        'function extractScriptText(json) {\n' +
        "  if (typeof json.content === 'string' && json.content.trim()) return json.content;\n" +
        "  if (typeof json.output === 'string' && json.output.trim()) return json.output;\n" +
        "  if (typeof json.text === 'string' && json.text.trim()) return json.text;\n" +
        "  if (json.message && typeof json.message.content === 'string') return json.message.content;\n" +
        '  if (Array.isArray(json.output)) {\n' +
        '    for (const part of json.output) {\n' +
        "      if (typeof part.content === 'string') return part.content;\n" +
        '      if (Array.isArray(part.content)) {\n' +
        "        const withText = part.content.find(function (c) { return typeof c.text === 'string'; });\n" +
        '        if (withText) return withText.text;\n' +
        '      }\n' +
        '    }\n' +
        '  }\n' +
        "  return '';\n" +
        '}\n' +
        '\n' +
        'const raw = extractScriptText($json);\n' +
        'const boldPattern = /\\*\\*(.+?)\\*\\*/g;\n' +
        "let clean = '';\n" +
        'let lastIndex = 0;\n' +
        'const emphasisRanges = [];\n' +
        'let match;\n' +
        'while ((match = boldPattern.exec(raw)) !== null) {\n' +
        '  clean += raw.slice(lastIndex, match.index);\n' +
        '  const start = clean.length;\n' +
        '  clean += match[1];\n' +
        '  const end = clean.length;\n' +
        '  emphasisRanges.push([start, end]);\n' +
        '  lastIndex = boldPattern.lastIndex;\n' +
        '}\n' +
        'clean += raw.slice(lastIndex);\n' +
        '\n' +
        "const upstream = $('Normalize Input').item.json;\n" +
        '\n' +
        'return [{\n' +
        '  json: {\n' +
        '    cleanText: clean.trim(),\n' +
        '    emphasisRanges: emphasisRanges,\n' +
        '    topic: upstream.topic,\n' +
        '    voiceId: upstream.voiceId,\n' +
        '    scriptPath: upstream.scriptPath,\n' +
        '  },\n' +
        '}];',
    },
  },
  output: [
    {
      cleanText:
        'Every great idea starts with one bold question. Keep the message clear and always moving, because small words build big moments.',
      emphasisRanges: [[11, 15], [35, 43]],
      topic: 'A weekend trip to the mountains',
      voiceId: '21m00Tcm4TlvDq8ikWAM',
      scriptPath: '/data/scripts/burn_kinetic_subtitles.py',
    },
  ],
});

const elevenLabsVoiceover = node({
  type: 'n8n-nodes-base.httpRequest',
  version: 4.3,
  config: {
    name: 'ElevenLabs Voiceover',
    position: [1040, 0],
    parameters: {
      method: 'POST',
      url: expr(
        'https://api.elevenlabs.io/v1/text-to-speech/{{ $json.voiceId }}/with-timestamps'
      ),
      authentication: 'genericCredentialType',
      genericAuthType: 'httpHeaderAuth',
      sendBody: true,
      contentType: 'json',
      specifyBody: 'json',
      jsonBody: expr(
        '{{ { "text": $json.cleanText, "model_id": "eleven_multilingual_v2" } }}'
      ),
      options: {
        response: {
          response: {
            responseFormat: 'json',
          },
        },
      },
    },
    credentials: {
      httpHeaderAuth: newCredential('ElevenLabs API'),
    },
  },
  output: [
    {
      audio_base64: 'BASE64_AUDIO_DATA',
      alignment: {
        characters: ['E', 'v', 'e', 'r', 'y', ' ', 'g', 'r', 'e', 'a', 't'],
        character_start_times_seconds: [0, 0.06, 0.11, 0.15, 0.2, 0.26, 0.3, 0.35, 0.4, 0.46, 0.51],
        character_end_times_seconds: [0.06, 0.11, 0.15, 0.2, 0.26, 0.3, 0.35, 0.4, 0.46, 0.51, 0.58],
      },
    },
  ],
});

const buildKineticCues = node({
  type: 'n8n-nodes-base.code',
  version: 2,
  config: {
    name: 'Build Kinetic Cues',
    position: [1300, 0],
    parameters: {
      mode: 'runOnceForAllItems',
      language: 'javaScript',
      jsCode:
        'const resp = $input.all()[0].json;\n' +
        "const clean = $('Clean Script Text').item.json;\n" +
        'const emphasisRanges = clean.emphasisRanges || [];\n' +
        '\n' +
        'function isEmphasized(charIndex) {\n' +
        '  for (const range of emphasisRanges) {\n' +
        '    if (charIndex >= range[0] && charIndex < range[1]) return true;\n' +
        '  }\n' +
        '  return false;\n' +
        '}\n' +
        '\n' +
        'const chars = resp.alignment.characters;\n' +
        'const starts = resp.alignment.character_start_times_seconds;\n' +
        'const ends = resp.alignment.character_end_times_seconds;\n' +
        '\n' +
        'const words = [];\n' +
        'let current = null;\n' +
        'let charPos = 0;\n' +
        'for (let i = 0; i < chars.length; i++) {\n' +
        '  const ch = chars[i];\n' +
        '  if (/\\s/.test(ch)) {\n' +
        '    if (current) { words.push(current); current = null; }\n' +
        '    charPos += 1;\n' +
        '    continue;\n' +
        '  }\n' +
        '  if (!current) {\n' +
        "    current = { text: '', start: starts[i], end: ends[i], emphasis: false };\n" +
        '  }\n' +
        '  current.text += ch;\n' +
        '  current.end = ends[i];\n' +
        '  if (isEmphasized(charPos)) current.emphasis = true;\n' +
        '  charPos += 1;\n' +
        '}\n' +
        'if (current) words.push(current);\n' +
        '\n' +
        'const cues = [];\n' +
        'let group = [];\n' +
        'let groupStart = null;\n' +
        'function flushGroup() {\n' +
        '  if (!group.length) return;\n' +
        '  cues.push({\n' +
        '    start: groupStart,\n' +
        '    end: group[group.length - 1].end + 0.05,\n' +
        '    words: group.map(function (w) { return { t: w.text.toUpperCase(), e: w.emphasis }; }),\n' +
        '  });\n' +
        '  group = [];\n' +
        '}\n' +
        'for (const w of words) {\n' +
        '  if (!group.length) groupStart = w.start;\n' +
        '  group.push(w);\n' +
        '  if (w.emphasis || group.length >= 4) flushGroup();\n' +
        '}\n' +
        'flushGroup();\n' +
        '\n' +
        'const cuesPayload = { cues: cues };\n' +
        "const audioBuffer = Buffer.from(resp.audio_base64, 'base64');\n" +
        'const cuesBuffer = Buffer.from(JSON.stringify(cuesPayload, null, 2));\n' +
        '\n' +
        'return [{\n' +
        '  json: {\n' +
        '    topic: clean.topic,\n' +
        '    voiceId: clean.voiceId,\n' +
        '    scriptPath: clean.scriptPath,\n' +
        '    cueCount: cues.length,\n' +
        '  },\n' +
        '  binary: {\n' +
        '    voice: {\n' +
        "      data: audioBuffer.toString('base64'),\n" +
        "      mimeType: 'audio/mpeg',\n" +
        "      fileName: 'voice.mp3',\n" +
        '    },\n' +
        '    cues: {\n' +
        "      data: cuesBuffer.toString('base64'),\n" +
        "      mimeType: 'application/json',\n" +
        "      fileName: 'cues.json',\n" +
        '    },\n' +
        '  },\n' +
        '}];',
    },
  },
  output: [
    {
      topic: 'A weekend trip to the mountains',
      voiceId: '21m00Tcm4TlvDq8ikWAM',
      scriptPath: '/data/scripts/burn_kinetic_subtitles.py',
      cueCount: 5,
    },
  ],
});

const preparePaths = node({
  type: 'n8n-nodes-base.code',
  version: 2,
  config: {
    name: 'Prepare Paths',
    position: [1560, 0],
    parameters: {
      mode: 'runOnceForAllItems',
      language: 'javaScript',
      jsCode:
        'const upstream = $json;\n' +
        "const workDir = '/tmp/n8n-vlog-' + $execution.id;\n" +
        '\n' +
        'return [{\n' +
        '  json: {\n' +
        '    workDir: workDir,\n' +
        "    videoPath: workDir + '/input.mp4',\n" +
        "    audioPath: workDir + '/voice.mp3',\n" +
        "    cuesPath: workDir + '/cues.json',\n" +
        "    outPath: workDir + '/final.mp4',\n" +
        '    scriptPath: upstream.scriptPath,\n' +
        '  },\n' +
        '}];',
    },
  },
  output: [
    {
      workDir: '/tmp/n8n-vlog-123',
      videoPath: '/tmp/n8n-vlog-123/input.mp4',
      audioPath: '/tmp/n8n-vlog-123/voice.mp3',
      cuesPath: '/tmp/n8n-vlog-123/cues.json',
      outPath: '/tmp/n8n-vlog-123/final.mp4',
      scriptPath: '/data/scripts/burn_kinetic_subtitles.py',
    },
  ],
});

const makeWorkDir = node({
  type: 'n8n-nodes-base.ssh',
  version: 1,
  config: {
    name: 'Make Work Dir',
    position: [1820, 0],
    executeOnce: true,
    parameters: {
      resource: 'command',
      operation: 'execute',
      authentication: 'password',
      command: expr('mkdir -p "{{ $json.workDir }}"'),
    },
    credentials: {
      sshPassword: newCredential('SSH Password'),
    },
  },
  output: [{ code: 0, signal: null, stdout: '', stderr: '' }],
});

const attachFilesBinary = node({
  type: 'n8n-nodes-base.code',
  version: 2,
  config: {
    name: 'Attach Files Binary',
    position: [2080, 0],
    parameters: {
      mode: 'runOnceForAllItems',
      language: 'javaScript',
      jsCode:
        "const paths = $('Prepare Paths').item.json;\n" +
        '\n' +
        'return [{\n' +
        '  json: paths,\n' +
        '  binary: {\n' +
        "    video: $('Normalize Input').item.binary.video,\n" +
        "    voice: $('Build Kinetic Cues').item.binary.voice,\n" +
        "    cues: $('Build Kinetic Cues').item.binary.cues,\n" +
        '  },\n' +
        '}];',
    },
  },
  output: [
    {
      workDir: '/tmp/n8n-vlog-123',
      videoPath: '/tmp/n8n-vlog-123/input.mp4',
      audioPath: '/tmp/n8n-vlog-123/voice.mp3',
      cuesPath: '/tmp/n8n-vlog-123/cues.json',
      outPath: '/tmp/n8n-vlog-123/final.mp4',
      scriptPath: '/data/scripts/burn_kinetic_subtitles.py',
    },
  ],
});

const uploadVideo = node({
  type: 'n8n-nodes-base.ssh',
  version: 1,
  config: {
    name: 'Upload Video',
    position: [2340, -160],
    parameters: {
      resource: 'file',
      operation: 'upload',
      authentication: 'password',
      binaryPropertyName: 'video',
      path: expr('{{ $json.workDir }}'),
      options: { fileName: 'input.mp4' },
    },
    credentials: {
      sshPassword: newCredential('SSH Password'),
    },
  },
  output: [{ success: true }],
});

const uploadVoiceover = node({
  type: 'n8n-nodes-base.ssh',
  version: 1,
  config: {
    name: 'Upload Voiceover',
    position: [2340, 0],
    parameters: {
      resource: 'file',
      operation: 'upload',
      authentication: 'password',
      binaryPropertyName: 'voice',
      path: expr('{{ $json.workDir }}'),
      options: { fileName: 'voice.mp3' },
    },
    credentials: {
      sshPassword: newCredential('SSH Password'),
    },
  },
  output: [{ success: true }],
});

const uploadCues = node({
  type: 'n8n-nodes-base.ssh',
  version: 1,
  config: {
    name: 'Upload Cues',
    position: [2340, 160],
    parameters: {
      resource: 'file',
      operation: 'upload',
      authentication: 'password',
      binaryPropertyName: 'cues',
      path: expr('{{ $json.workDir }}'),
      options: { fileName: 'cues.json' },
    },
    credentials: {
      sshPassword: newCredential('SSH Password'),
    },
  },
  output: [{ success: true }],
});

const filesUploaded = merge({
  version: 3.2,
  config: {
    name: 'Files Uploaded',
    position: [2600, 0],
    parameters: { mode: 'append', numberInputs: 3 },
  },
});

const renderKineticSubtitles = node({
  type: 'n8n-nodes-base.ssh',
  version: 1,
  config: {
    name: 'Render Kinetic Subtitles',
    position: [2860, 0],
    executeOnce: true,
    parameters: {
      resource: 'command',
      operation: 'execute',
      authentication: 'password',
      command: expr(
        'python3 "{{ $(\'Prepare Paths\').item.json.scriptPath }}" --video "{{ $(\'Prepare Paths\').item.json.videoPath }}" --cues "{{ $(\'Prepare Paths\').item.json.cuesPath }}" --voiceover "{{ $(\'Prepare Paths\').item.json.audioPath }}" --out "{{ $(\'Prepare Paths\').item.json.outPath }}"'
      ),
    },
    credentials: {
      sshPassword: newCredential('SSH Password'),
    },
  },
  output: [{ code: 0, signal: null, stdout: 'Wrote /tmp/n8n-vlog-123/final.mp4', stderr: '' }],
});

const downloadFinalVideo = node({
  type: 'n8n-nodes-base.ssh',
  version: 1,
  config: {
    name: 'Download Final Video',
    position: [3120, 0],
    parameters: {
      resource: 'file',
      operation: 'download',
      authentication: 'password',
      path: expr("{{ $('Prepare Paths').item.json.outPath }}"),
      binaryPropertyName: 'data',
    },
    credentials: {
      sshPassword: newCredential('SSH Password'),
    },
  },
  output: [{ code: 0, signal: null, stdout: '', stderr: '' }],
});

const respondWithVideo = node({
  type: 'n8n-nodes-base.respondToWebhook',
  version: 1.1,
  config: {
    name: 'Respond With Video',
    position: [3380, 0],
    parameters: {
      respondWith: 'binary',
      responseDataSource: 'set',
      inputFieldName: 'data',
      options: {
        responseHeaders: {
          entries: [{ name: 'Content-Type', value: 'video/mp4' }],
        },
      },
    },
  },
  output: [{}],
});

export default workflow('vlog-kinetic-subtitles', 'AI Vlog Kinetic Subtitles')
  .add(webhookTrigger)
  .to(normalizeInput)
  .to(generateScript)
  .to(cleanScriptText)
  .to(elevenLabsVoiceover)
  .to(buildKineticCues)
  .to(preparePaths)
  .to(makeWorkDir)
  .to(attachFilesBinary)
  .to(uploadVideo.to(filesUploaded.input(0)))
  .add(attachFilesBinary)
  .to(uploadVoiceover.to(filesUploaded.input(1)))
  .add(attachFilesBinary)
  .to(uploadCues.to(filesUploaded.input(2)))
  .add(filesUploaded)
  .to(renderKineticSubtitles)
  .to(downloadFinalVideo)
  .to(respondWithVideo);
