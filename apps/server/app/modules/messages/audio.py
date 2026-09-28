"""Keep recorded instructions separate from uploaded audio material."""


def command_ids(result):
    return set(result.get('voiceCommandAttachmentIds') or ([result['voiceCommandAttachmentId']] if result.get('voiceCommandAttachmentId') else []))


def audio_header(index, name):
    return f'【语音 {index + 1}：{name}】\n'


def audio_order(result):
    if 'audioSources' in result:
        return [item['id'] for item in result['audioSources']]
    parts = result.get('audioTranscripts', {})
    return [identifier for identifier in result.get('attachmentOrder', list(parts)) if identifier in parts]


def joined_transcript(result):
    parts, order = result['audioTranscripts'], audio_order(result)
    if len(order) == 1:
        return parts[order[0]]['text']
    return '\n\n'.join(audio_header(index, parts[identifier]['name']) + parts[identifier]['text'] for index, identifier in enumerate(order))


def transcript_groups(transcript, result):
    """Return (instructions, reference). Corrections retain each source's role."""
    if not transcript:
        return '', ''
    selected, parts, order = command_ids(result), result.get('audioTranscripts', {}), audio_order(result)
    if not order:
        return (transcript, '') if selected else ('', transcript)
    if not selected.intersection(order):
        return '', transcript
    if selected.issuperset(order):
        return transcript, ''
    if all(identifier in parts for identifier in order) and transcript == joined_transcript(result):
        # ASR text may itself mention a heading. Split generated output using
        # stored file IDs, never using words spoken in an uploaded recording.
        groups = [[], []]
        for index, identifier in enumerate(order):
            part = parts[identifier]
            groups[0 if identifier in selected else 1].append(audio_header(index, part['name']) + part['text'])
        return '\n\n'.join(groups[0]), '\n\n'.join(groups[1])
    # Mixed recorded/uploaded speech cannot share one authorization flag.
    # The editable transcript keeps these visible per-file headings.
    names = {identifier: part['name'] for identifier, part in parts.items()}
    names.update({item['id']: item['name'] for item in result.get('audioSources', [])})
    if any(transcript.count(audio_header(index, names[identifier])) != 1 for index, identifier in enumerate(order)):
        raise ValueError('修正混合语音时，请为每段语音保留一个标题，避免重复标题混淆来源')
    remaining, instructions, material = transcript, [], []
    for index, identifier in enumerate(order):
        header = audio_header(index, names[identifier])
        if not remaining.startswith(header):
            raise ValueError('修正混合语音时，请保留每段“【语音 …】”标题，以区分录音指令和上传材料')
        remaining = remaining[len(header):]
        if index + 1 < len(order):
            next_header = audio_header(index + 1, names[order[index + 1]])
            body, separator, tail = remaining.partition('\n\n' + next_header)
            if not separator:
                raise ValueError('修正混合语音时，请保留每段“【语音 …】”标题，以区分录音指令和上传材料')
            remaining = next_header + tail
        else:
            body = remaining
        (instructions if identifier in selected else material).append(header + body.strip())
    return '\n\n'.join(instructions), '\n\n'.join(material)
