"""Single transactional business layer for the isolated Research Workflow Studio."""
import json
import math
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

FIELDS = ('goal', 'foundations', 'approach', 'resources', 'consensus')
STAGES = ('idea', 'formal', 'ablation')
TYPES = ('research', 'experiment', 'code', 'run', 'artifact', 'protocol', 'dataset',
         'evaluation', 'comparison', 'analysis', 'report', 'conversation', 'proposal', 'usage', 'spec', 'amendment')
STATES = ('planned', 'running', 'completed', 'failed', 'partial')
RESULT_KINDS = ('metric', 'series', 'image-set', 'table', 'attachment')
RECORD_OPS = {
    'rws_research_save': 'research', 'rws_experiment_save': 'experiment',
    'rws_code_register': 'code', 'rws_run_register': 'run',
    'rws_artifact_register': 'artifact', 'rws_protocol_register': 'protocol',
    'rws_dataset_register': 'dataset', 'rws_conversation_save': 'conversation',
    'rws_evaluation_import': 'evaluation', 'rws_comparison_save': 'comparison',
    'rws_analysis_save': 'analysis', 'rws_report_create_revision': 'report',
    'rws_spec_save': 'spec',
}
IMMUTABLE = {'code', 'artifact', 'protocol', 'dataset', 'conversation', 'evaluation'}
HUMAN_ONLY = {'rws_overview_apply', 'rws_overview_dismiss', 'rws_project_stages_set', 'rws_amendment_apply', 'rws_amendment_dismiss'}
READS = {'rws_project_list', 'rws_record_get', 'rws_get_context', 'rws_code_find', 'rws_result_query'}
ALLOWED_FIELDS = {
    'research': {'title', 'question', 'hypothesis', 'kind', 'stage', 'parentRefs', 'judgment', 'status', 'implementationLinks'},
    'experiment': {'title', 'researchRef', 'protocolRef', 'config', 'status', 'foundationRevision'},
    'code': {'title', 'kind', 'version', 'source', 'parentRefs', 'description', 'specRef', 'entrypoint', 'modulePath', 'repository', 'commit', 'capabilities', 'checkEvidence'},
    'run': {'title', 'kind', 'codeRef', 'manual', 'config', 'status', 'inputRefs', 'experimentRef', 'source', 'notes', 'sampleSelection', 'purpose'},
    'artifact': {'title', 'kind', 'producerRef', 'sampleId', 'config', 'uri', 'availability', 'content', 'description', 'provenance', 'source', 'semantic', 'observation', 'inputRefs', 'datasetRef', 'taskKey'},
    'protocol': {'title', 'version', 'metrics', 'preprocessing', 'aggregation', 'missingPolicy', 'inputRequirements', 'inputKind', 'description'},
    'dataset': {'title', 'version', 'sampleIds', 'split', 'description'},
    'conversation': {'title', 'uri', 'summary', 'researchRef', 'experimentRef'},
    'evaluation': {'title', 'protocolRef', 'codeRef', 'inputRefs', 'results', 'status', 'experimentRef', 'datasetRef', 'sampleStatuses', 'pairs', 'config', 'notes'},
    'comparison': {'title', 'inputRefs', 'fixedConditions', 'varyingConditions', 'description', 'viewSpec'},
    'analysis': {'title', 'experimentRefs', 'inputRefs', 'observations', 'interpretation', 'limitations', 'codeRef', 'runRef', 'comparisonRefs', 'scope', 'coverage'},
    'report': {'title', 'inputRefs', 'analysisRefs', 'evaluationRefs', 'researchRefs', 'markdown', 'comparisonRefs', 'generatorCodeRef', 'generatorRunRef'},
    'spec': {'title', 'schemaVersion', 'kind', 'status', 'purpose', 'inputs', 'outputs', 'configSchema', 'dependencies', 'acceptanceChecks', 'capabilities'},
}

CODE_KINDS = ('inference', 'evaluation', 'analysis', 'report')
IMPLEMENTATION_ROLES = ('implementation', 'control', 'diagnostic')
AMENDMENT_FIELDS = {'title', 'description', 'parentRefs', 'source', 'provenance', 'producerRef', 'inputRefs', 'recoveredByRef', 'semantic', 'datasetRef', 'sampleId', 'taskKey', 'observation', 'sampleSelection', 'purpose'}


class RwsError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details

    def as_dict(self):
        out = {'code': self.code, 'message': self.message}
        if self.details is not None:
            out['details'] = self.details
        return out


def fail(message, code='validation_error', details=None):
    raise RwsError(code, message, details)


def now():
    return datetime.now(timezone.utc).isoformat()


def dump(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError):
        fail('Only finite, JSON-compatible data is accepted.')


def ident(value, label='id'):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', value):
        fail(label + ' must be a nonempty safe identifier (maximum 128 characters).')
    return value


def text(value, label, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        fail(label + ' must be a string' + ('.' if allow_empty else ' and must not be empty.'))
    return value


def integer(value, label, minimum=1):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        fail(label + ' must be an integer >= ' + str(minimum) + '.')
    return value


def array(value, label):
    if not isinstance(value, list):
        fail(label + ' must be an array.')
    return value


def object_(value, label):
    if not isinstance(value, dict):
        fail(label + ' must be an object.')
    return value


def ref_schema(kind=None):
    return {'type': 'object', 'properties': {'projectId': {'type': 'string'}, 'type': {'type': 'string', 'enum': [kind] if kind else list(TYPES)}, 'id': {'type': 'string'}, 'version': {'type': 'integer', 'minimum': 1}}, 'required': ['projectId', 'type', 'id'], 'additionalProperties': False}


def implementation_links_schema():
    target = ref_schema()
    target['properties']['type']['enum'] = ['spec', 'code']
    target['required'].append('version')
    return {'type': 'array', 'maxItems': 32, 'description': 'Declared research purposes, not actual execution or evidence. Pin a specification before implementation, or reference existing code. Omission preserves existing links; [] clears them.',
            'items': {'type': 'object', 'properties': {
                'targetRef': target, 'role': {'enum': list(IMPLEMENTATION_ROLES)},
                'note': {'type': 'string', 'maxLength': 1000}},
                'required': ['targetRef', 'role'], 'additionalProperties': False}}


def typed_result_schema():
    string = {'type': 'string'}
    axis = {'type': 'object', 'properties': {'label': {'type': 'string', 'minLength': 1}, 'unit': string}, 'required': ['label', 'unit'], 'additionalProperties': False}
    common = {'name': string, 'label': string, 'sampleId': string, 'sourceRef': ref_schema()}
    def variant(kind, properties, required, **more):
        result = {'type': 'object', 'properties': dict(common, kind={'const': kind}, **properties), 'required': ['kind'] + required, 'additionalProperties': False}
        result.update(more)
        return result
    metric = variant('metric', {'metricId': string, 'value': {'type': ['number', 'null']}, 'unit': string, 'direction': {'enum': ['higher', 'lower', 'higher-is-better', 'lower-is-better', 'none', 'target']}, 'sampleIds': {'type': 'array', 'items': string, 'uniqueItems': True}, 'aggregation': string, 'status': {'enum': ['completed', 'missing', 'failed', 'undefined']}, 'reason': string}, ['value'], anyOf=[{'required': ['name']}, {'required': ['metricId']}])
    series = variant('series', {'xAxis': axis, 'yAxis': axis, 'x': axis, 'y': axis, 'points': {'type': 'array', 'items': {'anyOf': [{'type': 'object', 'properties': {'x': {'type': 'number'}, 'y': {'type': 'number'}}, 'required': ['x', 'y'], 'additionalProperties': False}, {'type': 'array', 'items': {'type': 'number'}, 'minItems': 2, 'maxItems': 2}]}}}, ['points'], anyOf=[{'required': ['xAxis', 'yAxis']}, {'required': ['x', 'y']}])
    image = variant('image-set', {'items': {'type': 'array', 'items': {'type': 'object', 'properties': {'artifactRef': ref_schema('artifact'), 'uri': string, 'sampleId': string, 'caption': string, 'config': {'type': 'object', 'additionalProperties': True}}, 'anyOf': [{'required': ['artifactRef']}, {'required': ['uri']}], 'additionalProperties': False}}}, ['items'])
    table = variant('table', {'columns': {'type': 'array', 'items': {'type': 'object', 'properties': {'key': string, 'name': string, 'label': string, 'type': {'enum': ['string', 'number', 'boolean']}, 'metricId': string, 'unit': string}, 'required': ['type'], 'anyOf': [{'required': ['key']}, {'required': ['name']}], 'additionalProperties': False}}, 'rows': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': {'type': ['string', 'number', 'boolean', 'null']}}}}, ['columns', 'rows'])
    attachment = variant('attachment', {'uri': string, 'mimeType': string, 'mediaType': string, 'availability': {'enum': ['available', 'unavailable', 'unknown']}, 'description': string}, ['uri'], anyOf=[{'required': ['mimeType']}, {'required': ['mediaType']}])
    return {'oneOf': [metric, series, image, table, attachment]}


def record_schema(kind, partial=False):
    string = {'type': 'string'}
    text_list = {'oneOf': [string, {'type': 'array', 'items': string}]}
    references = {'type': 'array', 'items': ref_schema()}
    strings = {'type': 'array', 'items': {'type': 'string', 'minLength': 1}, 'uniqueItems': True}
    observation = {'type': 'object', 'properties': {'step': {'type': 'number', 'minimum': 0}, 'time': {'type': 'number'}, 'label': string}, 'additionalProperties': False}
    port = {'type': 'object', 'properties': {'name': {'type': 'string', 'minLength': 1}, 'kind': {'type': 'string', 'minLength': 1}, 'semantic': {'type': 'string', 'minLength': 1}, 'required': {'type': 'boolean'}, 'multiple': {'type': 'boolean'}, 'description': string}, 'required': ['name', 'kind'], 'additionalProperties': False}
    props = {
        'id': {'type': 'string', 'pattern': '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'},
        'title': {'type': 'string', 'minLength': 1}, 'question': {'type': 'string', 'minLength': 1},
        'hypothesis': {'type': ['string', 'null'], 'minLength': 1, 'description': 'A concrete hypothesis. Explicit null clears an optional statement; omission preserves it when updating. Judged research remains subject to human review.'}, 'version': {'type': 'string', 'minLength': 1},
        'stage': {'enum': list(STAGES)}, 'status': {'enum': list(STATES)},
        'source': {'oneOf': [{'type': 'string', 'minLength': 1}, {'type': 'object', 'minProperties': 1, 'additionalProperties': True}]},
        'config': {'type': 'object', 'additionalProperties': True}, 'manual': {'type': 'boolean'},
        'judgment': {'description': 'Human scientific decision. Explicit null removes it only with human authority; omission preserves the previous decision.', 'oneOf': [{'type': 'null'}, string, {'type': 'object', 'properties': {'label': string, 'summary': string, 'evidenceRefs': references, 'limitations': text_list}, 'required': ['label'], 'additionalProperties': False}]},
        'foundationRevision': {'type': 'integer', 'minimum': 1}, 'uri': string, 'sampleId': string,
        'availability': {'enum': ['available', 'unavailable', 'unknown']}, 'content': typed_result_schema(),
        'provenance': {'enum': ['known', 'unresolved'], 'description': 'known requires an actual producer run; unresolved preserves legacy outputs with source evidence and a description of what remains unknown.'},
        'description': string, 'summary': string, 'notes': string, 'split': string,
        'sampleIds': {'type': 'array', 'items': string, 'uniqueItems': True},
        'metrics': {'type': 'array', 'items': {'type': 'object', 'properties': {'id': string, 'name': string, 'label': string, 'unit': string, 'direction': {'enum': ['higher', 'lower', 'higher-is-better', 'lower-is-better', 'none', 'target']}, 'granularity': {'enum': ['sample', 'dataset', 'aggregate']}, 'min': {'type': 'number'}, 'max': {'type': 'number'}}, 'required': ['unit', 'direction', 'granularity'], 'anyOf': [{'required': ['id']}, {'required': ['name']}], 'additionalProperties': False}},
        'preprocessing': {'oneOf': [string, {'type': 'object', 'additionalProperties': True}]},
        'aggregation': {'oneOf': [string, {'type': 'object', 'additionalProperties': True}]},
        'missingPolicy': {'oneOf': [string, {'type': 'object', 'additionalProperties': True}]},
        'inputRequirements': {'oneOf': [string, {'type': 'object', 'additionalProperties': True}]},
        'inputKind': {'enum': ['artifact', 'paired-image', 'dataset']},
        'results': {'type': 'array', 'items': typed_result_schema()},
        'pairs': {'type': 'array', 'items': {'type': 'object', 'properties': {'sampleId': string, 'predictionRef': ref_schema(), 'referenceRef': ref_schema()}, 'required': ['sampleId', 'predictionRef', 'referenceRef'], 'additionalProperties': False}},
        'sampleStatuses': {'type': 'array', 'items': {'type': 'object', 'properties': {'sampleId': string, 'status': {'enum': ['completed', 'failed', 'missing']}, 'reason': string}, 'required': ['sampleId', 'status'], 'additionalProperties': False}},
        'fixedConditions': {'type': 'object', 'additionalProperties': True},
        'varyingConditions': {'oneOf': [{'type': 'array', 'items': string}, {'type': 'object', 'additionalProperties': True}]},
        'observations': text_list, 'interpretation': string, 'limitations': text_list, 'markdown': string,
        'schemaVersion': {'type': 'integer', 'const': 1}, 'purpose': {'type': 'string', 'minLength': 1},
        'implementationLinks': implementation_links_schema(),
        'inputs': {'type': 'array', 'items': port}, 'outputs': {'type': 'array', 'items': port},
        'configSchema': {'type': 'object'}, 'dependencies': references, 'capabilities': strings,
        'acceptanceChecks': {'type': 'array', 'items': {'type': 'object', 'properties': {'id': {'type': 'string', 'minLength': 1}, 'description': {'type': 'string', 'minLength': 1}}, 'required': ['id', 'description'], 'additionalProperties': False}},
        'checkEvidence': {'type': 'array', 'items': {'type': 'object', 'properties': {'checkId': {'type': 'string', 'minLength': 1}, 'status': {'enum': ['passed', 'failed', 'skipped']}, 'evidence': {'type': 'string', 'minLength': 1}}, 'required': ['checkId', 'status', 'evidence'], 'additionalProperties': False}},
        'entrypoint': {'type': 'string', 'minLength': 1}, 'modulePath': {'type': 'string', 'minLength': 1},
        'repository': {'type': 'string', 'minLength': 1}, 'commit': {'type': 'string', 'minLength': 1},
        'sampleSelection': {'type': 'object', 'properties': {'datasetRef': ref_schema('dataset'), 'sampleIds': strings}, 'required': ['sampleIds'], 'additionalProperties': False},
        'semantic': {'type': 'string', 'minLength': 1}, 'observation': observation, 'taskKey': {'type': 'string', 'minLength': 1},
        'viewSpec': {'type': 'object', 'properties': {'mode': {'enum': ['single', 'multi']}, 'sampleIds': strings, 'semantics': strings, 'axis': string, 'selectedValues': {'type': 'array'}, 'observation': observation, 'filters': {'type': 'object'}, 'repeats': {'enum': ['all', 'latest']}}, 'required': ['mode'], 'additionalProperties': False},
        'scope': {'type': 'object', 'properties': {'sampleIds': strings, 'description': string}, 'additionalProperties': False},
        'coverage': {'type': 'object', 'properties': {'expected': {'type': 'integer', 'minimum': 0}, 'observed': {'type': 'integer', 'minimum': 0}, 'missingSampleIds': strings}, 'required': ['expected', 'observed'], 'additionalProperties': False},
    }
    for field in ('researchRef', 'protocolRef', 'codeRef', 'experimentRef', 'producerRef', 'datasetRef', 'runRef', 'specRef', 'generatorCodeRef', 'generatorRunRef'):
        props[field] = ref_schema()
    for field in ('parentRefs', 'inputRefs', 'experimentRefs', 'analysisRefs', 'evaluationRefs', 'researchRefs', 'comparisonRefs'):
        props[field] = references
    kinds = {'research': ['hypothesis', 'exploration', 'reproduction'], 'code': list(CODE_KINDS), 'spec': list(CODE_KINDS)}
    props['kind'] = {'enum': kinds[kind]} if kind in kinds else {'type': 'string', 'minLength': 1}
    required = {'research': ['question'], 'experiment': ['researchRef'], 'code': ['kind', 'version', 'source'], 'run': [], 'artifact': ['kind'], 'protocol': ['version', 'metrics', 'preprocessing', 'aggregation', 'missingPolicy'], 'dataset': ['version', 'sampleIds'], 'conversation': ['uri'], 'evaluation': ['protocolRef', 'codeRef', 'inputRefs', 'results'], 'comparison': ['inputRefs', 'fixedConditions', 'varyingConditions'], 'analysis': ['observations', 'limitations'], 'report': ['markdown'], 'spec': ['schemaVersion', 'kind', 'status', 'purpose', 'inputs', 'outputs', 'configSchema', 'dependencies', 'acceptanceChecks', 'capabilities']}[kind]
    if kind == 'spec':
        props['status'] = {'enum': ['draft', 'ready']}
    schema = {'type': 'object', 'properties': {field: props[field] for field in sorted(ALLOWED_FIELDS[kind] | {'id'})}, 'required': ['title'] + required, 'additionalProperties': False}
    if kind == 'run':
        schema['anyOf'] = [{'required': ['codeRef']}, {'properties': {'manual': {'const': True}}, 'required': ['manual']}]
    if kind == 'artifact':
        schema['anyOf'] = [{'properties': {'provenance': {'const': 'known'}}, 'required': ['producerRef']}, {'properties': {'provenance': {'const': 'unresolved'}}, 'required': ['provenance', 'source', 'description']}]
    if kind == 'research':
        schema['if'] = {'properties': {'kind': {'const': 'hypothesis'}}, 'required': ['kind']}
        schema['then'] = {'required': ['hypothesis']}
    if kind == 'code':
        schema['if'] = {'required': ['specRef']}
        schema['then'] = {'required': ['entrypoint', 'modulePath', 'repository', 'commit', 'capabilities', 'checkEvidence']}
    if partial and kind not in IMMUTABLE:
        full = schema
        schema = {'type': 'object', 'properties': full['properties'], 'additionalProperties': False,
                  'anyOf': [{'required': ['id']}, full],
                  'description': 'For an existing id, provide only fields to change; omitted fields are preserved. A new id still requires a complete valid record.'}
    return schema


def tool_definitions():
    s = {'type': 'string'}
    refs = {'type': 'array', 'items': ref_schema()}
    common = {'requestId': s, 'projectId': s, 'expectedRevision': {'type': 'integer', 'minimum': 1}}
    descriptions = {
        'rws_research_save': 'Save a research question or optional hypothesis. implementationLinks declares intended uses of exact spec/code revisions before execution; these links are not evidence and do not decide scientific validity.',
        'rws_experiment_save': 'Save an experiment and bind its confirmed project foundation; does not execute it.',
        'rws_code_register': 'Register an immutable code identity and explicit parent references; never reads or runs the path.',
        'rws_run_register': 'Record an actual run and status. Registration never launches a program; producer bindings are immutable.',
        'rws_artifact_register': 'Register an immutable output with its actual producer and configuration. For a legacy output with unresolved provenance, explicitly set provenance=unresolved with source evidence and a description; never invent a producer run. Does not read arbitrary files.',
        'rws_protocol_register': 'Register immutable evaluation metric definitions, preprocessing, aggregation and missing-data policy.',
        'rws_dataset_register': 'Register an immutable dataset version and exact sample IDs.',
        'rws_conversation_save': 'Register an existing conversation reference; does not create or send a chat.',
        'rws_evaluation_import': 'Validate and register existing typed evaluation results with fixed protocol/code/input versions; does not compute metrics.',
        'rws_comparison_save': 'Save exact comparison inputs and fixed/varying conditions without moving their original producers.',
        'rws_analysis_save': 'Save observations, interpretation and limitations; manual analysis may omit code.',
        'rws_report_create_revision': 'Create a report version with immutable foundation and transitive evidence snapshots.',
        'rws_spec_save': 'Define a method-level contract before implementation. Saves a new draft or ready revision; implementations pin an exact ready revision. Cases/configurations belong to runs, not method contracts.',
    }
    definitions = []
    def add(name, props, required, description, read=False):
        definitions.append({'name': name, 'description': description, 'inputSchema': {'type': 'object', 'properties': props, 'required': required, 'additionalProperties': False}, 'annotations': {'readOnlyHint': read, 'destructiveHint': False, 'idempotentHint': True, 'openWorldHint': False}})
    add('rws_project_list', {}, [], 'List projects and confirmed foundations.', True)
    add('rws_record_get', {'ref': ref_schema()}, ['ref'], 'Read one exact record or historical version.', True)
    add('rws_get_context', {'projectId': s, 'researchRef': ref_schema(), 'experimentRef': ref_schema(), 'selectionRefs': refs}, ['projectId'], 'Read concise project/task context, completed facts, pending gaps and suggested actions. Suggestions are not execution authorization.', True)
    add('rws_code_find', {'projectId': s, 'query': s, 'kind': {'enum': list(CODE_KINDS)}, 'specRef': ref_schema('spec'), 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 200}}, ['projectId'], 'Find existing implementations before building new code. Returns exact identities and declared contracts; supplied check evidence is not independent verification.', True)
    add('rws_result_query', {'projectId': s, 'sampleIds': {'type': 'array', 'items': s}, 'semantics': {'type': 'array', 'items': s}, 'codeRefs': {'type': 'array', 'items': ref_schema('code')}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 200}, 'offset': {'type': 'integer', 'minimum': 0}}, ['projectId'], 'Find exact outputs across runs in this project. Retains producer, case, configuration and observation coordinates; never silently merges repeats.', True)
    add('rws_project_create', {'requestId': s, 'name': s, 'goal': s, 'domain': s, 'projectId': s, 'demo': {'type': 'boolean'}}, ['requestId', 'name'], 'Create an independent project and its initial confirmed foundation; no demonstration records are inherited.')
    for name, kind in RECORD_OPS.items():
        add(name, dict(common, record=record_schema(kind, partial=True)), list(common) + ['record'], descriptions[name])
    add('rws_usage_save', dict(common, id=s, experimentRef=ref_schema(), artifactRefs=refs, role=s, label=s), list(common) + ['experimentRef', 'artifactRefs', 'role'], 'Reference precise artifacts in a target experiment, including cross-project reuse. Original producer remains unchanged.')
    add('rws_usage_remove', dict(common, id=s), list(common) + ['id'], 'Revoke a material usage without deleting source artifacts or other uses.')
    add('rws_overview_propose', dict(common, fields={'type': 'object', 'properties': {f: s for f in FIELDS}, 'additionalProperties': False}, reason=s, sourceRefs=refs, baseRevision={'type': 'integer', 'minimum': 1}), list(common) + ['fields', 'reason', 'baseRevision'], 'Save a proposed foundation revision for human review; this does not apply it.')
    for name in ('rws_overview_apply', 'rws_overview_dismiss'):
        add(name, dict(common, proposalRef=ref_schema(), baseRevision={'type': 'integer', 'minimum': 1}), list(common) + ['proposalRef', 'baseRevision'], 'Human review only. MCP cannot approve its own suggestion; use the application review screen.')
    add('rws_project_stages_set', dict(common, activeStages={'type': 'array', 'items': {'enum': list(STAGES)}}), list(common) + ['activeStages'], 'Human-only current-stage decision. Browsing and completed runs never advance stages.')
    amendment = {'type': 'object', 'properties': {'title': s, 'targetRef': ref_schema(), 'patch': {'type': 'object', 'minProperties': 1}, 'reason': s, 'evidenceRefs': refs}, 'required': ['title', 'targetRef', 'patch', 'reason', 'evidenceRefs'], 'additionalProperties': False}
    add('rws_amendment_propose', dict(common, record=amendment), list(common) + ['record'], 'Propose an audited metadata/source/lineage/recovery correction for an exact record. Does not rewrite the source or approve the correction.')
    add('rws_amendment_apply', dict(common, amendmentRef=ref_schema('amendment')), list(common) + ['amendmentRef'], 'Human-only approval of an exact pending amendment. Raw records and previous report snapshots remain unchanged.')
    add('rws_amendment_dismiss', dict(common, amendmentRef=ref_schema('amendment')), list(common) + ['amendmentRef'], 'Human-only dismissal of an exact pending amendment. Keeps the proposal history without applying its patch.')
    return definitions


def validate_schema(value, schema, path='arguments'):
    """Validate the small JSON Schema subset used in our published tool contracts."""
    def matches(candidate):
        try:
            validate_schema(value, candidate, path)
            return True
        except RwsError:
            return False
    if 'const' in schema and value != schema['const']:
        fail(path + ' must equal the specified constant.')
    if 'enum' in schema and value not in schema['enum']:
        fail(path + ' is not a supported value.')
    checks = {'object': lambda v: isinstance(v, dict), 'array': lambda v: isinstance(v, list), 'string': lambda v: isinstance(v, str), 'boolean': lambda v: isinstance(v, bool), 'null': lambda v: v is None, 'integer': lambda v: isinstance(v, int) and not isinstance(v, bool), 'number': lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)}
    types = schema.get('type', [])
    types = [types] if isinstance(types, str) else types
    if types and not any(checks[t](value) for t in types):
        fail(path + ' has an incorrect value type.')
    if 'anyOf' in schema and not any(matches(branch) for branch in schema['anyOf']):
        fail(path + ' does not match a supported input form.')
    if 'oneOf' in schema and sum(matches(branch) for branch in schema['oneOf']) != 1:
        fail(path + ' must match exactly one supported input form.')
    if 'if' in schema and matches(schema['if']):
        validate_schema(value, schema.get('then', {}), path)
    if isinstance(value, dict):
        missing = [k for k in schema.get('required', []) if k not in value]
        if missing:
            fail(path + ' is missing required fields.', details={'fields': missing})
        props = schema.get('properties', {})
        extra = set(value) - set(props)
        if extra and schema.get('additionalProperties') is False:
            fail(path + ' has unsupported fields.', details={'fields': sorted(extra)})
        if len(value) < schema.get('minProperties', 0):
            fail(path + ' must not be empty.')
        for key, child in value.items():
            if key in props:
                validate_schema(child, props[key], path + '.' + key)
            elif isinstance(schema.get('additionalProperties'), dict):
                validate_schema(child, schema['additionalProperties'], path + '.' + key)
    if isinstance(value, list):
        if len(value) < schema.get('minItems', 0) or len(value) > schema.get('maxItems', len(value)):
            fail(path + ' has an invalid number of items.')
        if schema.get('uniqueItems') and len({dump(v) for v in value}) != len(value):
            fail(path + ' must not contain duplicates.')
        if 'items' in schema:
            for index, child in enumerate(value):
                validate_schema(child, schema['items'], path + '[' + str(index) + ']')
    if isinstance(value, str):
        if len(value) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', len(value)) or ('pattern' in schema and re.search(schema['pattern'], value) is None):
            fail(path + ' has an invalid string value.')
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get('minimum', value) or value > schema.get('maximum', value):
            fail(path + ' is outside its allowed range.')


class Store:
    tool_definitions = staticmethod(tool_definitions)

    def __init__(self, db_path):
        self.db_path = str(db_path)
        self.uri = self.db_path == ':memory:'
        if self.uri:
            self.db_path = 'file:rws-' + uuid.uuid4().hex + '?mode=memory&cache=shared'
        else:
            Path(self.db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._anchor = self._connect()
        self._anchor.execute('PRAGMA journal_mode=WAL')
        self._anchor.executescript('''
            CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS records (project_id TEXT NOT NULL, type TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL, document TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(project_id,type,id,version), FOREIGN KEY(project_id) REFERENCES projects(id));
            CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, payload TEXT NOT NULL, result TEXT NOT NULL);
        ''')
        self._anchor.commit()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, uri=self.uri, timeout=20, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=20000')
        return conn

    def close(self):
        self._anchor.close()

    def _project(self, conn, pid):
        ident(pid, 'projectId')
        row = conn.execute('SELECT document FROM projects WHERE id=?', (pid,)).fetchone()
        if not row:
            fail('Project does not exist.', 'not_found', {'projectId': pid})
        return json.loads(row['document'])

    def _projects(self, conn):
        projects = [json.loads(row['document']) for row in conn.execute('SELECT document FROM projects ORDER BY id')]
        for project in projects:
            records = self._latest(conn, project['id'])
            project['summary'] = {
                'researchCount': sum(e['ref']['type'] == 'research' for e in records),
                'completedRunCount': sum(e['ref']['type'] == 'run' and e['record'].get('status') == 'completed' for e in records),
                'plannedExperimentCount': sum(e['ref']['type'] == 'experiment' and e['record'].get('status') == 'planned' for e in records),
                'evaluationCount': sum(e['ref']['type'] == 'evaluation' for e in records),
                'artifactCount': sum(e['ref']['type'] == 'artifact' for e in records),
            }
        return projects

    def _get(self, conn, ref, types=None, project=None):
        object_(ref, 'reference')
        if set(ref) - {'projectId', 'type', 'id', 'version'} or not {'projectId', 'type', 'id'}.issubset(ref):
            fail('Reference must explicitly contain projectId, type and id, with optional version.')
        pid, kind, rid = ident(ref['projectId'], 'reference.projectId'), ref['type'], ident(ref['id'], 'reference.id')
        if kind not in TYPES or (types and kind not in types):
            fail('Reference has an unsupported or unexpected type.', details={'type': kind, 'expected': types})
        if project and pid != project:
            fail('This relation must target the specified project.', details={'projectId': project})
        params = [pid, kind, rid]
        query = 'SELECT * FROM records WHERE project_id=? AND type=? AND id=?'
        if 'version' in ref:
            params.append(integer(ref['version'], 'reference.version'))
            query += ' AND version=?'
        row = conn.execute(query + ' ORDER BY version DESC LIMIT 1', params).fetchone()
        if not row:
            fail('Referenced record/version does not exist.', 'not_found', {'ref': ref})
        return {'ref': {'projectId': pid, 'type': kind, 'id': rid, 'version': row['version']}, 'record': json.loads(row['document']), 'createdAt': row['created_at']}

    def _latest(self, conn, pid):
        rows = conn.execute('''SELECT r.* FROM records r JOIN (SELECT type,id,MAX(version) v FROM records WHERE project_id=? GROUP BY type,id) x ON r.type=x.type AND r.id=x.id AND r.version=x.v WHERE r.project_id=? ORDER BY r.type,r.id''', (pid, pid))
        return [{'ref': {'projectId': pid, 'type': row['type'], 'id': row['id'], 'version': row['version']}, 'record': json.loads(row['document']), 'createdAt': row['created_at']} for row in rows]

    def _freeze(self, conn, value):
        if isinstance(value, dict):
            if {'projectId', 'type', 'id'}.issubset(value) and all(isinstance(value[k], str) for k in ('projectId', 'type', 'id')) and set(value) <= {'projectId', 'type', 'id', 'version'}:
                return self._get(conn, value)['ref']
            return {k: self._freeze(conn, v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._freeze(conn, v) for v in value]
        return value

    def _walk_refs(self, value):
        if isinstance(value, dict):
            if {'projectId', 'type', 'id'}.issubset(value) and all(isinstance(value[k], str) for k in ('projectId', 'type', 'id')) and set(value) <= {'projectId', 'type', 'id', 'version'}:
                yield value
            else:
                for v in value.values():
                    yield from self._walk_refs(v)
        elif isinstance(value, list):
            for v in value:
                yield from self._walk_refs(v)

    def _closure(self, conn, values):
        queue = list(self._walk_refs(values))
        seen, result = set(), []
        while queue:
            ref = queue.pop(0)
            env = self._get(conn, ref)
            key = dump(env['ref'])
            if key in seen:
                continue
            seen.add(key)
            result.append(env)
            queue.extend(self._walk_refs(env['record']))
        return result

    def _report_records(self, conn, record):
        # One exact envelope per dependency. Old reports keep their own foundation
        # and reference this outer closure instead of recursively duplicating it.
        records = self._closure(conn, record)
        # Corrections are separate facts. Pin their exact approved versions and
        # the effective projection now, never read them live from an old report.
        records = self._effective_many(conn, records)
        extra = self._closure(conn, [env.get('amendmentRefs', []) for env in records])
        keys = {dump(env['ref']) for env in records}
        records += [env for env in extra if dump(env['ref']) not in keys]
        for envelope in records:
            if envelope['ref']['type'] != 'report':
                continue
            snapshot = envelope['record'].get('snapshot', {})
            if 'records' in snapshot:
                snapshot['recordRefs'] = [item['ref'] for item in snapshot.pop('records')]
        return records

    def _report_snapshot(self, conn, project, record):
        records = self._report_records(conn, record)
        foundations = {}
        def add(project_id, revision):
            key = (project_id, revision)
            if key not in foundations:
                owner = project if project_id == project['id'] else self._project(conn, project_id)
                foundation = next((v for v in owner['versions'] if v['revision'] == revision), None)
                if foundation is None:
                    fail('A report dependency names an unavailable project foundation revision.')
                foundations[key] = {'projectId': project_id, 'foundation': foundation}
        add(project['id'], project['versions'][-1]['revision'])
        for envelope in records:
            value, ref = envelope['record'], envelope['ref']
            if ref['type'] == 'experiment':
                add(ref['projectId'], value['foundationRevision'])
            elif ref['type'] == 'report' and value.get('snapshot', {}).get('foundation'):
                add(ref['projectId'], value['snapshot']['foundation']['revision'])
        return {'foundation': project['versions'][-1], 'projectFoundations': list(foundations.values()), 'records': records}

    def _put(self, conn, pid, kind, record):
        rid = ident(record.get('id') or kind + '-' + uuid.uuid4().hex[:16])
        record['id'] = rid
        row = conn.execute('SELECT MAX(version) v FROM records WHERE project_id=? AND type=? AND id=?', (pid, kind, rid)).fetchone()
        version = (row['v'] or 0) + 1
        at = now()
        conn.execute('INSERT INTO records VALUES (?,?,?,?,?,?)', (pid, kind, rid, version, dump(record), at))
        return {'ref': {'projectId': pid, 'type': kind, 'id': rid, 'version': version}, 'record': record, 'createdAt': at}

    def snapshot(self, project_id=None):
        conn = self._connect()
        try:
            conn.execute('BEGIN')
            projects = self._projects(conn)
            if project_id is None:
                return {'projects': projects, 'projectId': None, 'revision': None, 'records': [], 'references': []}
            project = self._project(conn, project_id)
            records = self._latest(conn, project_id)
            own_keys = {dump(e['ref']) for e in records}
            references = [e for e in self._closure(conn, [e['record'] for e in records]) if dump(e['ref']) not in own_keys]
            projected = self._effective_many(conn, records + references)
            return {'projects': projects, 'projectId': project_id, 'revision': project['revision'], 'records': projected[:len(records)], 'references': projected[len(records):]}
        finally:
            conn.close()

    def call(self, name, arguments, actor='model'):
        if actor not in ('model', 'human'):
            fail('Unknown actor.', 'permission_denied')
        definition = next((t for t in tool_definitions() if t['name'] == name), None)
        if not definition:
            fail('Unknown operation.', 'not_found')
        args = json.loads(dump(object_(arguments, 'arguments')))
        schema = definition['inputSchema']
        validate_schema(args, schema)
        if set(args) - set(schema['properties']):
            fail('Unexpected operation arguments.', details={'fields': sorted(set(args) - set(schema['properties']))})
        missing = [k for k in schema['required'] if k not in args]
        if missing:
            fail('Required arguments are missing.', details={'fields': missing})
        if name in HUMAN_ONLY and actor != 'human':
            destination = 'stages' if name == 'rws_project_stages_set' else 'amendments' if name.startswith('rws_amendment_') else 'review'
            fail('Review and confirm this exact change in the application.', 'approval_required', {'reviewUrl': '/?' + urlencode({'projectId': str(args.get('projectId', '')), destination: '1'})})
        conn = self._connect()
        try:
            if name in READS:
                conn.execute('BEGIN')
                if name == 'rws_project_list':
                    result = self._projects(conn)
                elif name == 'rws_record_get':
                    result = self._effective(conn, self._get(conn, args['ref']))
                elif name == 'rws_code_find':
                    result = self._code_find(conn, args)
                elif name == 'rws_result_query':
                    result = self._result_query(conn, args)
                else:
                    result = self._context(conn, args)
                return {'ok': True, 'operation': name, 'result': result}
            request_id = ident(args['requestId'], 'requestId')
            payload = dump({'operation': name, 'arguments': args, 'actor': actor})
            conn.execute('BEGIN IMMEDIATE')
            prior = conn.execute('SELECT payload,result FROM requests WHERE id=?', (request_id,)).fetchone()
            if prior:
                if prior['payload'] != payload:
                    fail('requestId was already used for another request.', 'idempotency_conflict')
                return json.loads(prior['result'])
            if name == 'rws_project_create':
                result = self._create_project(conn, args)
                pid, revision = result['id'], result['revision']
            else:
                pid = args['projectId']
                project = self._project(conn, pid)
                if integer(args['expectedRevision'], 'expectedRevision') != project['revision']:
                    fail('Project changed. Reload and review before saving.', 'revision_conflict', {'currentRevision': project['revision']})
                result = self._mutate(conn, name, args, actor, project)
                project['revision'] += 1
                revision = project['revision']
                conn.execute('UPDATE projects SET revision=?,document=? WHERE id=?', (revision, dump(project), pid))
            response = {'ok': True, 'operation': name, 'projectId': pid, 'revision': revision, 'result': result, 'guidance': self._write_guidance(conn, name, pid, result)}
            conn.execute('INSERT INTO requests VALUES (?,?,?)', (request_id, payload, dump(response)))
            conn.commit()
            return response
        except sqlite3.IntegrityError:
            fail('An object with this identity already exists.', 'conflict')
        except sqlite3.OperationalError as error:
            raise RwsError('storage_error', 'Storage operation failed; no success was recorded.') from error
        finally:
            conn.close()

    def _write_guidance(self, conn, operation, pid, result):
        # Scope comes only from the saved object's explicit relations, never UI selection.
        args = {'projectId': pid}
        affected = result.get('ref') if isinstance(result, dict) else None
        if affected:
            args['selectionRefs'] = [affected]
            record = result['record']
            kind = affected['type']
            if kind == 'research':
                args['researchRef'] = affected
            elif kind == 'experiment':
                args['experimentRef'] = affected
            else:
                experiment_refs = []
                if record.get('experimentRef'):
                    experiment_refs.append(record['experimentRef'])
                experiment_refs.extend(record.get('experimentRefs', []))
                if kind == 'artifact' and record.get('producerRef'):
                    producer = self._get(conn, record['producerRef'])['record']
                    if producer.get('experimentRef'):
                        experiment_refs.append(producer['experimentRef'])
                unique = {dump(ref): ref for ref in experiment_refs if ref['projectId'] == pid}
                if len(unique) == 1:
                    args['experimentRef'] = next(iter(unique.values()))
                elif not unique:
                    research_refs = ([record['researchRef']] if record.get('researchRef') else []) + record.get('researchRefs', [])
                    own_research = {dump(ref): ref for ref in research_refs if ref['projectId'] == pid}
                    if len(own_research) == 1:
                        args['researchRef'] = next(iter(own_research.values()))
        context = self._context(conn, args)
        card = {key: context[key] for key in ('projectId', 'projectName', 'revision', 'position', 'latestFoundationRevision', 'currentResearchRef', 'currentResearch', 'researchVersionNotice', 'suggestedActions', 'notice')}
        card['foundationRevision'] = context['foundation']['revision']
        card['affectedRef'] = affected
        card['scope'] = 'affected-experiment' if args.get('experimentRef') else 'affected-research' if args.get('researchRef') else 'project'
        for key, limit in (('objects', 12), ('completed', 8), ('pending', 8)):
            card[key] = context[key][:limit]
            card[key + 'Count'] = context.get('objectCount', len(context[key])) if key == 'objects' else len(context[key])
            card[key + 'Truncated'] = card[key + 'Count'] > len(card[key])
        card['readMore'] = {'operation': 'rws_get_context', 'arguments': args}
        if operation == 'rws_overview_propose':
            card['suggestedActions'] = [{'label': '审阅项目基础修改建议', 'reason': '建议已保存，只有你确认后才会改变项目基础。', 'operation': 'rws_overview_apply', 'targetRef': affected, 'requiresHuman': True, 'reviewUrl': '/?' + urlencode({'projectId': pid, 'review': '1'})}]
        elif operation == 'rws_amendment_propose':
            card['suggestedActions'] = [{'label': '审阅来源修正', 'reason': '原始记录保持不变；确认后才应用有审计记录的显示修正。', 'operation': 'rws_amendment_apply', 'targetRef': affected, 'requiresHuman': True, 'reviewUrl': '/?' + urlencode({'projectId': pid, 'amendments': '1'})}]
        elif operation == 'rws_spec_save':
            card['suggestedActions'] = [{'label': '查找可复用实现', 'reason': '先检查已有实现及其固定契约；需要新实现时按本契约编写和检查。', 'operation': 'rws_code_find', 'targetRef': affected}]
        elif operation == 'rws_code_register':
            card['suggestedActions'] = [{'label': '准备输入与配置', 'reason': '同一实现可用于多个 case 和配置；核对契约后，实际执行仍由对话确认。', 'operation': 'rws_run_register', 'targetRef': affected}]
        return card

    def _create_project(self, conn, args):
        name = text(args['name'], 'name')
        pid = ident(args.get('projectId') or 'project-' + uuid.uuid4().hex[:16], 'projectId')
        if 'demo' in args and not isinstance(args['demo'], bool):
            fail('demo must be boolean.')
        goal = text(args.get('goal', ''), 'goal', True)
        domain = text(args.get('domain', '研究项目'), 'domain', True)
        project = {'id': pid, 'name': name, 'domain': domain, 'demo': args.get('demo', False), 'revision': 1, 'activeStages': [], 'stagesConfirmedAt': None, 'versions': [{'revision': 1, 'at': now(), 'origin': '项目创建', 'fields': {f: goal if f == 'goal' else '' for f in FIELDS}}], 'draft': None}
        conn.execute('INSERT INTO projects VALUES (?,?,?)', (pid, 1, dump(project)))
        return project

    def _mutate(self, conn, name, args, actor, project):
        pid = project['id']
        if name in RECORD_OPS:
            return self._save_record(conn, RECORD_OPS[name], args['record'], actor, project)
        if name in ('rws_amendment_propose', 'rws_amendment_apply', 'rws_amendment_dismiss'):
            return self._amend(conn, name, args, project)
        if name == 'rws_project_stages_set':
            stages = array(args['activeStages'], 'activeStages')
            if any(s not in STAGES for s in stages) or len(stages) != len(set(stages)):
                fail('Stages must be unique supported stage names.')
            project['activeStages'] = [s for s in STAGES if s in stages]
            project['stagesConfirmedAt'] = now()
            return {'activeStages': project['activeStages'], 'stagesConfirmedAt': project['stagesConfirmedAt']}
        if name == 'rws_usage_save':
            experiment = self._get(conn, args['experimentRef'], ['experiment'], pid)
            refs = [self._get(conn, r, ['artifact'])['ref'] for r in array(args['artifactRefs'], 'artifactRefs')]
            if not refs or len({dump(r) for r in refs}) != len(refs):
                fail('Choose a nonempty list of unique exact artifacts.')
            record = {'experimentRef': experiment['ref'], 'artifactRefs': refs, 'role': text(args['role'], 'role'), 'label': text(args.get('label', ''), 'label', True), 'revoked': False}
            if 'id' in args:
                record['id'] = ident(args['id'])
            return self._put(conn, pid, 'usage', record)
        if name == 'rws_usage_remove':
            env = self._get(conn, {'projectId': pid, 'type': 'usage', 'id': args['id']})
            record = env['record']
            if record.get('revoked'):
                fail('Usage is already revoked.', 'conflict')
            record['revoked'] = True
            return self._put(conn, pid, 'usage', record)
        if name == 'rws_overview_propose':
            base = integer(args['baseRevision'], 'baseRevision')
            if base != project['versions'][-1]['revision']:
                fail('Foundation changed; review the current version.', 'revision_conflict')
            fields = object_(args['fields'], 'fields')
            if not fields or set(fields) - set(FIELDS):
                fail('Provide supported foundation fields only.')
            for k, v in fields.items():
                text(v, k, True)
            merged = dict(project['versions'][-1]['fields'], **fields)
            record = {'baseRevision': base, 'fields': merged, 'reason': text(args['reason'], 'reason'), 'sourceRefs': [self._get(conn, r)['ref'] for r in array(args.get('sourceRefs', []), 'sourceRefs')]}
            env = self._put(conn, pid, 'proposal', record)
            project['draft'] = {'proposalRef': env['ref'], 'baseRevision': base, 'fields': merged, 'origin': record['reason'], 'at': env['createdAt']}
            return env
        if name in ('rws_overview_apply', 'rws_overview_dismiss'):
            draft = project['draft']
            env = self._get(conn, args['proposalRef'], ['proposal'], pid)
            if not draft or env['ref'] != draft['proposalRef']:
                fail('The reviewed proposal is no longer the active draft.', 'revision_conflict')
            if args['proposalRef'].get('version') != env['ref']['version']:
                fail('Human review must identify the exact proposal version.')
            base = integer(args['baseRevision'], 'baseRevision')
            if base != project['versions'][-1]['revision'] or base != env['record']['baseRevision']:
                fail('The foundation changed since this proposal was reviewed.', 'revision_conflict')
            if name.endswith('_apply'):
                project['versions'].append({'revision': base + 1, 'at': now(), 'origin': env['record']['reason'], 'fields': env['record']['fields'], 'proposalRef': env['ref']})
            project['draft'] = None
            return {'foundation': project['versions'][-1], 'draft': None}
        fail('Operation is not implemented.', 'not_found')

    def _amendment_index(self, conn, pid):
        rows = conn.execute('''SELECT r.* FROM records r JOIN
            (SELECT id, MAX(version) v FROM records WHERE project_id=? AND type='amendment' GROUP BY id) x
            ON r.id=x.id AND r.version=x.v WHERE r.project_id=? AND r.type='amendment' ''', (pid, pid))
        index = {}
        for row in rows:
            record = json.loads(row['document'])
            if record.get('status') != 'approved':
                continue
            env = {'ref': {'projectId': pid, 'type': 'amendment', 'id': row['id'], 'version': row['version']}, 'record': record, 'createdAt': row['created_at']}
            index.setdefault(dump(record['targetRef']), []).append(env)
        for items in index.values():
            items.sort(key=lambda item: (item['record'].get('approvedAt', ''), item['ref']['id']))
        return index

    def _effective_many(self, conn, envelopes):
        indexes = {env['ref']['projectId']: None for env in envelopes}
        for pid in indexes:
            indexes[pid] = self._amendment_index(conn, pid)
        return [self._effective(conn, env, indexes[env['ref']['projectId']]) for env in envelopes]

    def _effective(self, conn, envelope, amendment_index=None):
        """Return an overlay alongside the original document, never instead of it."""
        env = json.loads(dump(envelope))
        ref = env['ref']
        if ref['type'] in ('amendment', 'report'):
            return env
        if amendment_index is None:
            amendment_index = self._amendment_index(conn, ref['projectId'])
        amendments = amendment_index.get(dump(ref), [])
        if not amendments:
            return env
        effective = json.loads(dump(env['record']))
        for item in amendments:
            effective.update(item['record']['patch'])
        env['effectiveRecord'] = effective
        env['amendmentRefs'] = [item['ref'] for item in amendments]
        return env

    def _code_find(self, conn, args):
        self._project(conn, args['projectId'])
        spec = self._get(conn, args['specRef'], ['spec'])['ref'] if args.get('specRef') else None
        query = args.get('query', '').casefold().strip()
        items = []
        for env in self._latest(conn, args['projectId']):
            if env['ref']['type'] != 'code':
                continue
            env = self._effective(conn, env)
            record = env.get('effectiveRecord', env['record'])
            if args.get('kind') and record['kind'] != args['kind']:
                continue
            if spec and record.get('specRef') != spec:
                continue
            if query and query not in ' '.join(str(record.get(k, '')) for k in ('title', 'description', 'capabilities', 'entrypoint')).casefold():
                continue
            items.append(env)
        limit = args.get('limit', 50)
        return {'items': items[:limit], 'total': len(items), 'limit': limit,
                'notice': 'Check evidence was supplied by the registering client; registration does not execute or verify code.'}

    def _result_query(self, conn, args):
        self._project(conn, args['projectId'])
        codes = {dump(self._get(conn, ref, ['code'])['ref']) for ref in args.get('codeRefs', [])}
        samples, semantics = set(args.get('sampleIds', [])), set(args.get('semantics', []))
        items = []
        for env in self._latest(conn, args['projectId']):
            if env['ref']['type'] != 'artifact':
                continue
            env = self._effective(conn, env)
            record = env.get('effectiveRecord', env['record'])
            if samples and record.get('sampleId') not in samples:
                continue
            if semantics and record.get('semantic') not in semantics:
                continue
            code_ref = None
            if record.get('producerRef'):
                producer = self._effective(conn, self._get(conn, record['producerRef'], ['run']))
                code_ref = producer.get('effectiveRecord', producer['record']).get('codeRef')
            if codes and dump(code_ref) not in codes:
                continue
            env['codeRef'] = code_ref
            items.append(env)
        offset, limit = args.get('offset', 0), args.get('limit', 100)
        return {'items': items[offset:offset + limit], 'total': len(items), 'offset': offset, 'limit': limit}

    def _validate_amendment(self, conn, target, patch):
        kind = target['ref']['type']
        if kind not in ('research', 'experiment', 'code', 'run', 'artifact', 'dataset', 'conversation', 'comparison', 'analysis'):
            fail('This record type cannot be amended; create an explicit new revision where supported.')
        allowed = AMENDMENT_FIELDS & (ALLOWED_FIELDS[kind] | {'recoveredByRef'})
        if set(patch) - allowed:
            fail('Correction cannot change execution identity, evidence, or a scientific decision.', details={'fields': sorted(set(patch) - allowed)})
        projected = self._effective(conn, target)
        effective = projected.get('effectiveRecord', projected['record'])
        value = dict(effective, **patch)
        props = record_schema(kind)['properties']
        for field, item in patch.items():
            if field in props:
                validate_schema(item, props[field], 'patch.' + field)
        for key in ('title', 'description'):
            if key in patch:
                text(patch[key], key, key == 'description')
        if 'source' in patch and (not isinstance(patch['source'], (str, dict)) or not patch['source']):
            fail('A source correction needs nonempty source evidence.')
        if 'parentRefs' in patch:
            for ref in array(patch['parentRefs'], 'parentRefs'):
                self._get(conn, ref, [kind], target['ref']['projectId'] if kind == 'research' else None)
            if len({dump(ref) for ref in patch['parentRefs']}) != len(patch['parentRefs']):
                fail('Parent references must be unique.')
            self._check_effective_dag(conn, target, value)
        if 'inputRefs' in patch:
            for ref in array(patch['inputRefs'], 'inputRefs'):
                self._get(conn, ref)
        if 'producerRef' in patch:
            producer = self._get(conn, patch['producerRef'], ['run'], target['ref']['projectId'])
            if producer['record'].get('status') == 'planned':
                fail('A planned run cannot be the corrected producer.')
        if kind == 'artifact':
            if value.get('provenance', 'known') not in ('known', 'unresolved'):
                fail('Unsupported corrected provenance.')
            if value.get('provenance', 'known') == 'known' and not value.get('producerRef'):
                fail('Known corrected provenance requires an actual producer.')
            if value.get('provenance') == 'unresolved' and not value.get('source'):
                fail('Unresolved corrected provenance needs source evidence.')
            self._validate_case_selection(conn, value)
            self._validate_artifact_contract(conn, target['ref']['projectId'], value, exclude_ref=target['ref'])
        if kind == 'run' and 'sampleSelection' in patch:
            self._validate_case_selection(conn, value['sampleSelection'])
            self._validate_run_contract(conn, value)
        if 'recoveredByRef' in patch:
            if kind != 'run' or target['record'].get('status') not in ('failed', 'partial'):
                fail('Only failed or partial runs can declare a recovery.')
            recovery = self._effective(conn, self._get(conn, patch['recoveredByRef'], ['run'], target['ref']['projectId']))
            recovered_record = recovery.get('effectiveRecord', recovery['record'])
            if recovery['ref']['id'] == target['ref']['id'] or recovery['record'].get('status') != 'completed':
                fail('Recovery must identify another completed run.')
            for field in ('codeRef', 'config', 'inputRefs', 'sampleSelection', 'experimentRef'):
                if value.get(field) != recovered_record.get(field):
                    fail('Recovery must preserve the failed run scope and implementation.', details={'field': field})

    def _check_effective_dag(self, conn, target, value):
        kind, pid = target['ref']['type'], target['ref']['projectId']
        def key(ref):
            return (ref['projectId'], ref['type'], ref['id'])
        root = key(target['ref'])
        active, done = set(), set()
        def visit(ref):
            identity = key(ref)
            if identity in active:
                fail('Corrected lineage must not contain a cycle.')
            if identity in done:
                return
            active.add(identity)
            projected = self._effective(conn, self._get(conn, ref, [kind]))
            record = value if identity == root else projected.get('effectiveRecord', projected['record'])
            for parent in record.get('parentRefs', []):
                visit(parent)
            active.remove(identity)
            done.add(identity)
        visit(target['ref'])

    def _amend(self, conn, name, args, project):
        pid = project['id']
        if name == 'rws_amendment_propose':
            record = args['record']
            text(record['title'], 'title')
            text(record['reason'], 'reason')
            if 'version' not in record['targetRef']:
                fail('An amendment must identify the exact target version.')
            target = self._get(conn, record['targetRef'], project=pid)
            patch = self._freeze(conn, record['patch'])
            self._validate_amendment(conn, target, patch)
            evidence = [self._get(conn, ref)['ref'] for ref in record['evidenceRefs']]
            return self._put(conn, pid, 'amendment', {'title': record['title'], 'targetRef': target['ref'], 'patch': patch, 'reason': record['reason'], 'evidenceRefs': evidence, 'status': 'pending', 'baseAmendmentRefs': self._effective(conn, target).get('amendmentRefs', [])})
        if 'version' not in args['amendmentRef']:
            fail('Review must identify the exact amendment version.')
        env = self._get(conn, args['amendmentRef'], ['amendment'], pid)
        latest = self._get(conn, {k: v for k, v in args['amendmentRef'].items() if k != 'version'})
        if env['ref'] != latest['ref'] or env['record']['status'] != 'pending':
            fail('This amendment is no longer pending.', 'revision_conflict')
        record = env['record']
        if name == 'rws_amendment_dismiss':
            record.update(status='dismissed', dismissedAt=now(), dismissedBy='human')
            return self._put(conn, pid, 'amendment', record)
        target = self._get(conn, record['targetRef'])
        if self._effective(conn, target).get('amendmentRefs', []) != record['baseAmendmentRefs']:
            fail('The target corrections changed after this proposal. Propose a new amendment.', 'revision_conflict')
        self._validate_amendment(conn, target, record['patch'])
        record.update(status='approved', approvedAt=now(), approvedBy='human')
        return self._put(conn, pid, 'amendment', record)

    def _save_record(self, conn, kind, value, actor, project):
        record = json.loads(dump(object_(value, 'record')))
        if set(record) - ALLOWED_FIELDS[kind] - {'id'}:
            fail('Unsupported fields for ' + kind + '.', details={'fields': sorted(set(record) - ALLOWED_FIELDS[kind] - {'id'})})
        pid = project['id']
        cleared = {field for field in ('hypothesis', 'judgment') if kind == 'research' and field in record and record[field] is None}
        if 'judgment' in cleared and actor != 'human':
            fail('Clearing a scientific judgment requires a human decision.', 'approval_required')
        old = None
        if 'id' in record:
            ident(record['id'])
            row = conn.execute('SELECT 1 FROM records WHERE project_id=? AND type=? AND id=?', (pid, kind, record['id'])).fetchone()
            if row:
                old = self._get(conn, {'projectId': pid, 'type': kind, 'id': record['id']})['record']
                if kind in IMMUTABLE:
                    fail('This registered source is immutable; register a new identity.', 'immutable_source')
                retained = {key: value for key, value in old.items() if key in ALLOWED_FIELDS[kind] or key == 'id'}
                record = dict(retained, **record)
        for field in cleared:
            record.pop(field, None)
        validate_schema(record, record_schema(kind), 'record')
        text(record.get('title'), 'record.title')
        record = self._freeze(conn, record)
        if kind == 'research':
            text(record.get('question'), 'question')
            record.setdefault('kind', 'exploration')
            record.setdefault('stage', 'idea')
            record.setdefault('parentRefs', [])
            if record['kind'] not in ('hypothesis', 'exploration', 'reproduction') or record['stage'] not in STAGES:
                fail('Unsupported research kind or stage.')
            if record.get('hypothesis') is not None:
                text(record['hypothesis'], 'hypothesis')
            if record['kind'] == 'hypothesis' and not record.get('hypothesis'):
                fail('A hypothesis research entry needs a stated hypothesis.')
            if old and actor != 'human':
                if record['stage'] != old.get('stage', 'idea'):
                    fail('Changing an existing research stage requires human confirmation.', 'approval_required')
                if old.get('judgment') is not None:
                    if any(record.get(k) != old.get(k) for k in ('question', 'hypothesis', 'kind')):
                        fail('Changing a judged research question requires human review.', 'approval_required')
                    record.setdefault('judgment', old['judgment'])
            if 'judgment' in record:
                if actor != 'human' and (not old or record['judgment'] != old.get('judgment')):
                    fail('Scientific judgments require a human decision.', 'approval_required')
                if not record.get('hypothesis'):
                    fail('Support/refutation cannot be assigned without a stated hypothesis.')
            for ref in array(record['parentRefs'], 'parentRefs'):
                self._get(conn, ref, ['research'], pid)
            seen_links = set()
            for link in record.get('implementationLinks', []):
                self._get(conn, link['targetRef'], ['spec', 'code'])
                identity = (dump(link['targetRef']), link['role'])
                if identity in seen_links:
                    fail('An implementation target and role may only be declared once.')
                seen_links.add(identity)
            self._check_dag(conn, pid, kind, record)
        elif kind == 'experiment':
            self._get(conn, record.get('researchRef'), ['research'], pid)
            if record.get('protocolRef'):
                self._get(conn, record['protocolRef'], ['protocol'])
            record.setdefault('config', {})
            object_(record['config'], 'config')
            record.setdefault('status', 'planned')
            self._status(record)
            foundation = old['foundationRevision'] if old else project['versions'][-1]['revision']
            if 'foundationRevision' in record and record['foundationRevision'] != foundation:
                fail('An experiment retains its original foundation binding.', 'immutable_source')
            if old and record['researchRef'] != old['researchRef']:
                fail('An experiment cannot move to another research entry.', 'immutable_source')
            record['foundationRevision'] = foundation
        elif kind == 'code':
            if record.get('kind') not in ('inference', 'evaluation', 'analysis', 'report'):
                fail('Unsupported code kind.')
            text(record.get('version'), 'version')
            if not isinstance(record.get('source'), (str, dict)) or not record['source']:
                fail('Describe the registered code source.')
            record.setdefault('parentRefs', [])
            for ref in array(record['parentRefs'], 'parentRefs'):
                self._get(conn, ref, ['code'])
            self._validate_code_contract(conn, pid, record)
        elif kind == 'run':
            record.setdefault('manual', False)
            if not isinstance(record['manual'], bool):
                fail('manual must be boolean.')
            if record.get('codeRef'):
                self._get(conn, record['codeRef'], ['code'])
            elif not record['manual']:
                fail('An actual run needs its codeRef, or an explicit manual record.')
            if record.get('experimentRef'):
                self._get(conn, record['experimentRef'], ['experiment'], pid)
            record.setdefault('kind', 'inference')
            record.setdefault('config', {})
            object_(record['config'], 'config')
            record.setdefault('inputRefs', [])
            array(record['inputRefs'], 'inputRefs')
            record.setdefault('status', 'planned')
            self._status(record)
            self._validate_run_contract(conn, record)
            if old:
                for field in ('codeRef', 'manual', 'config', 'inputRefs', 'experimentRef', 'kind', 'source', 'sampleSelection', 'purpose'):
                    if old.get(field) != record.get(field):
                        fail('Actual run code, inputs, configuration and source cannot change.', 'immutable_source', {'field': field})
        elif kind == 'artifact':
            record.setdefault('provenance', 'known')
            if record['provenance'] == 'known' and not record.get('producerRef'):
                fail('Known provenance requires its actual producerRef.')
            if record['provenance'] == 'unresolved':
                text(record.get('description'), 'description')
                source = record.get('source')
                if not isinstance(source, (str, dict)) or not source or (isinstance(source, str) and not source.strip()):
                    fail('Unresolved provenance requires nonempty original source evidence.')
            if record.get('producerRef'):
                producer = self._get(conn, record['producerRef'], ['run'], pid)
                if producer['record'].get('status') == 'planned':
                    fail('A planned run has no actual output to register.')
            text(record.get('kind'), 'kind')
            record.setdefault('config', {})
            object_(record['config'], 'config')
            if 'sampleId' in record:
                text(record['sampleId'], 'sampleId')
            record.setdefault('availability', 'unknown')
            if record['availability'] not in ('available', 'unavailable', 'unknown'):
                fail('Unsupported artifact availability.')
            if 'uri' in record:
                text(record['uri'], 'uri')
            if 'content' in record:
                self._result(record['content'], conn=conn)
            self._validate_artifact_contract(conn, pid, record)
        elif kind == 'spec':
            self._validate_spec(record)
        elif kind == 'protocol':
            text(record.get('version'), 'version')
            metrics = array(record.get('metrics'), 'metrics')
            names = set()
            for metric in metrics:
                object_(metric, 'metric definition')
                key = metric.get('id', metric.get('name'))
                text(key, 'metric.id/name')
                if key in names:
                    fail('Metric identities must be unique.')
                names.add(key)
                text(metric.get('unit'), 'metric.unit', True)
                if metric.get('direction') not in ('higher', 'lower', 'higher-is-better', 'lower-is-better', 'none', 'target'):
                    fail('Each metric needs an explicit direction.')
                if metric.get('granularity') not in ('sample', 'dataset', 'aggregate'):
                    fail('Each metric needs an explicit sample/dataset granularity.')
                if 'min' in metric and 'max' in metric and metric['min'] > metric['max']:
                    fail('Metric minimum must not exceed its maximum.')
            for field in ('preprocessing', 'aggregation', 'missingPolicy'):
                if field not in record:
                    fail('Protocol requires explicit ' + field + '.')
        elif kind == 'dataset':
            text(record.get('version'), 'version')
            samples = array(record.get('sampleIds'), 'sampleIds')
            if any(not isinstance(s, str) or not s for s in samples) or len(set(samples)) != len(samples):
                fail('Dataset sampleIds must be unique strings.')
        elif kind == 'conversation':
            text(record.get('uri'), 'uri')
            if record.get('researchRef'):
                self._get(conn, record['researchRef'], ['research'], pid)
            if record.get('experimentRef'):
                experiment = self._get(conn, record['experimentRef'], ['experiment'], pid)['record']
                if record.get('researchRef') and any(record['researchRef'][k] != experiment['researchRef'][k] for k in ('projectId', 'type', 'id')):
                    fail('Conversation research and experiment references do not match.')
        elif kind == 'evaluation':
            protocol = self._get(conn, record.get('protocolRef'), ['protocol'])['record']
            code = self._get(conn, record.get('codeRef'), ['code'])['record']
            if code['kind'] != 'evaluation':
                fail('Evaluation codeRef must name evaluation code.')
            if code.get('specRef'):
                spec = self._get(conn, code['specRef'], ['spec'])['record']
                validate_schema(record.get('config', {}), spec['configSchema'], 'evaluation.config')
                self._validate_contract_inputs(conn, spec, record['inputRefs'])
            inputs = [self._get(conn, r, ['artifact']) for r in array(record.get('inputRefs'), 'inputRefs')]
            if not inputs:
                fail('Evaluation requires fixed input artifacts.')
            if len({dump(item['ref']) for item in inputs}) != len(inputs):
                fail('Evaluation inputs must identify unique artifacts.')
            if record.get('experimentRef'):
                experiment = self._get(conn, record['experimentRef'], ['experiment'], pid)['record']
                if experiment.get('protocolRef') and experiment['protocolRef'] != record['protocolRef']:
                    fail('Evaluation protocol/version differs from the experiment protocol.')
            sample_ids = {e['record'].get('sampleId') for e in inputs} - {None}
            if record.get('datasetRef'):
                dataset = self._get(conn, record['datasetRef'], ['dataset'])['record']
                if not sample_ids <= set(dataset['sampleIds']):
                    fail('Input sample does not belong to the fixed dataset.')
            if protocol.get('inputKind') == 'paired-image' and any(not item['record'].get('sampleId') for item in inputs):
                fail('Every paired-image input needs an explicit sampleId.')
            pairs = array(record.get('pairs', []), 'pairs')
            if protocol.get('inputKind') == 'paired-image' and not pairs:
                fail('A paired-image protocol requires explicit prediction/reference pairs.')
            pair_ids, paired_input_keys = set(), set()
            input_keys = {dump(e['ref']) for e in inputs}
            for pair in pairs:
                object_(pair, 'pair')
                sid = pair.get('sampleId')
                if sid not in sample_ids or sid in pair_ids:
                    fail('Each pair needs a unique selected sampleId.')
                pair_ids.add(sid)
                for field in ('predictionRef', 'referenceRef'):
                    artifact = self._get(conn, pair.get(field), ['artifact'])
                    if dump(artifact['ref']) not in input_keys or artifact['record'].get('sampleId') != sid:
                        fail('Pair references must be fixed inputs for the declared sample.')
                    paired_input_keys.add(dump(artifact['ref']))
                if pair['predictionRef'] == pair['referenceRef']:
                    fail('Prediction and reference must be distinct artifacts.')
            if protocol.get('inputKind') == 'paired-image' and (pair_ids != sample_ids or paired_input_keys != input_keys):
                fail('Pairs must cover every selected input artifact and sample.')
            statuses = record.get('sampleStatuses', [])
            seen = set()
            failed = set()
            for status in array(statuses, 'sampleStatuses'):
                object_(status, 'sample status')
                sid = status.get('sampleId')
                if sid not in sample_ids or sid in seen:
                    fail('Sample status must identify a unique selected sample.')
                seen.add(sid)
                if status.get('status') not in ('completed', 'failed', 'missing'):
                    fail('Unsupported sample result status.')
                if status['status'] != 'completed':
                    text(status.get('reason'), 'failed/missing reason')
                    failed.add(sid)
            if statuses and seen != sample_ids:
                fail('Sample statuses must cover all selected samples.')
            metrics = {m.get('id', m.get('name')): m for m in protocol['metrics']}
            results = array(record.get('results'), 'results')
            metric_keys = set()
            covered = {key: set() for key in metrics}
            for result in results:
                self._result(result, metrics=metrics, sample_ids=sample_ids, conn=conn)
                if result['kind'] == 'metric':
                    metric = result.get('metricId', result.get('name'))
                    scope = [result['sampleId']] if result.get('sampleId') else sorted(result.get('sampleIds', []))
                    key = (metric, tuple(scope))
                    if key in metric_keys:
                        fail('Duplicate metric values for the same sample or aggregate are ambiguous.')
                    metric_keys.add(key)
                    if result.get('value') is not None:
                        covered[metric].update(scope if scope else sample_ids)
                if result.get('sampleId') in failed and result.get('value') is not None:
                    fail('Failed/missing sample cannot carry a numeric result.')
                if result.get('sampleIds') and set(result['sampleIds']) & failed:
                    fail('Aggregate cannot silently include failed samples.')
            record.setdefault('status', 'completed')
            self._status(record)
            if record['status'] == 'completed':
                if failed:
                    fail('Evaluation with failed samples must be partial or failed.')
                if not results:
                    fail('A completed evaluation must contain actual results.')
                for metric in metrics:
                    if not any(r['kind'] == 'metric' and r.get('metricId', r.get('name')) == metric and r.get('value') is not None for r in results):
                        fail('A completed evaluation must contain a value for every declared metric.')
                    if sample_ids and covered[metric] != sample_ids:
                        fail('A completed evaluation must cover every selected sample; otherwise mark it partial.')
            if record['status'] in ('failed', 'partial') and not results and not record.get('notes') and not failed:
                fail('An evaluation without results needs an explicit failure or missing-data reason.')
        elif kind == 'comparison':
            array(record.get('inputRefs'), 'inputRefs')
            object_(record.get('fixedConditions'), 'fixedConditions')
            if not isinstance(record.get('varyingConditions'), (list, dict)):
                fail('varyingConditions must explicitly describe allowed differences.')
            if len({dump(ref) for ref in record['inputRefs']}) != len(record['inputRefs']):
                fail('Comparison inputs must identify unique records.')
            if record.get('viewSpec', {}).get('mode') == 'single' and len(record['viewSpec'].get('sampleIds', [])) > 1:
                fail('Single-case view cannot select more than one sampleId.')
        elif kind == 'analysis':
            for ref in array(record.get('experimentRefs', []), 'experimentRefs'):
                self._get(conn, ref, ['experiment'], pid)
            array(record.get('inputRefs', []), 'inputRefs')
            if not isinstance(record.get('observations'), (str, list)):
                fail('Analysis must state observations separately.')
            text(record.get('interpretation', ''), 'interpretation', True)
            if not isinstance(record.get('limitations'), (str, list)):
                fail('Analysis must state its limitations.')
            if record.get('codeRef'):
                code = self._get(conn, record['codeRef'], ['code'])['record']
                if code['kind'] != 'analysis':
                    fail('Analysis codeRef must name analysis code.')
            if record.get('runRef'):
                run = self._get(conn, record['runRef'], ['run'])['record']
                if record.get('codeRef') and run.get('codeRef') != record['codeRef']:
                    fail('Analysis run and code references disagree.')
            for ref in record.get('comparisonRefs', []):
                self._get(conn, ref, ['comparison'])
            if record.get('coverage'):
                coverage = record['coverage']
                if coverage['observed'] > coverage['expected']:
                    fail('Observed coverage cannot exceed the declared scope.')
                missing = coverage.get('missingSampleIds', [])
                if len(missing) > coverage['expected'] - coverage['observed']:
                    fail('Missing sample count conflicts with declared coverage.')
                if record.get('scope', {}).get('sampleIds') and not set(missing) <= set(record['scope']['sampleIds']):
                    fail('Missing samples must belong to the stated analysis scope.')
        elif kind == 'report':
            text(record.get('markdown'), 'markdown', True)
            for field, types in (('inputRefs', None), ('analysisRefs', ['analysis']), ('evaluationRefs', ['evaluation']), ('researchRefs', ['research']), ('comparisonRefs', ['comparison'])):
                for ref in array(record.get(field, []), field):
                    self._get(conn, ref, types)
            if record.get('generatorCodeRef'):
                code = self._get(conn, record['generatorCodeRef'], ['code'])['record']
                if code['kind'] != 'report':
                    fail('Report generatorCodeRef must name report-generation code.')
            if record.get('generatorRunRef'):
                run = self._get(conn, record['generatorRunRef'], ['run'])['record']
                if run.get('status') not in ('completed', 'partial'):
                    fail('Report generatorRunRef must identify actual completed or partial work.')
                if not record.get('generatorCodeRef') or run.get('codeRef') != record['generatorCodeRef']:
                    fail('Report generator run and code references must agree.')
            record['foundationRevision'] = project['versions'][-1]['revision']
            record['snapshot'] = self._report_snapshot(conn, project, record)
        return self._put(conn, pid, kind, record)

    def _validate_config_schema(self, schema):
        """Reject unsupported keywords rather than silently ignoring a contract."""
        object_(schema, 'configSchema')
        allowed = {'type', 'properties', 'required', 'additionalProperties', 'items', 'enum', 'const',
                   'anyOf', 'oneOf', 'if', 'then', 'minProperties', 'minItems', 'maxItems', 'uniqueItems',
                   'minLength', 'pattern', 'minimum', 'maximum', 'description', 'title', 'default', '$schema'}
        if set(schema) - allowed:
            fail('configSchema uses unsupported validation keywords.', details={'keywords': sorted(set(schema) - allowed)})
        types = schema.get('type', [])
        types = [types] if isinstance(types, str) else types
        if not isinstance(types, list) or any(t not in ('object', 'array', 'string', 'number', 'integer', 'boolean', 'null') for t in types):
            fail('configSchema has an unsupported type.')
        if 'required' in schema and (not isinstance(schema['required'], list) or any(not isinstance(v, str) for v in schema['required'])):
            fail('configSchema.required must be a list of field names.')
        if 'enum' in schema and (not isinstance(schema['enum'], list) or not schema['enum']):
            fail('configSchema.enum must be a nonempty list.')
        if 'pattern' in schema:
            try:
                re.compile(schema['pattern'])
            except (TypeError, re.error):
                fail('configSchema.pattern must be a valid regular expression.')
        for key in ('minProperties', 'minItems', 'maxItems', 'minLength'):
            if key in schema:
                integer(schema[key], 'configSchema.' + key, 0)
        for key in ('minimum', 'maximum'):
            if key in schema and (isinstance(schema[key], bool) or not isinstance(schema[key], (int, float))):
                fail('configSchema bounds must be numbers.')
        if 'uniqueItems' in schema and not isinstance(schema['uniqueItems'], bool):
            fail('configSchema.uniqueItems must be boolean.')
        if 'additionalProperties' in schema and not isinstance(schema['additionalProperties'], (bool, dict)):
            fail('configSchema.additionalProperties must be a boolean or schema.')
        for child in object_(schema.get('properties', {}), 'configSchema.properties').values():
            self._validate_config_schema(child)
        for key in ('items', 'if', 'then'):
            if key in schema:
                self._validate_config_schema(schema[key])
        if isinstance(schema.get('additionalProperties'), dict):
            self._validate_config_schema(schema['additionalProperties'])
        for key in ('anyOf', 'oneOf'):
            if key in schema:
                if not array(schema[key], key):
                    fail('configSchema alternatives cannot be empty.')
                for child in schema[key]:
                    self._validate_config_schema(child)

    def _validate_spec(self, record):
        for field in ('inputs', 'outputs'):
            names = [p['name'] for p in record[field]]
            if len(set(names)) != len(names):
                fail('Contract port names must be unique within ' + field + '.')
        check_ids = [c['id'] for c in record['acceptanceChecks']]
        if len(set(check_ids)) != len(check_ids):
            fail('Acceptance check IDs must be unique.')
        if record['status'] == 'ready' and (not record['outputs'] or not check_ids):
            fail('A ready contract requires declared outputs and acceptance checks.')
        self._validate_config_schema(record['configSchema'])

    def _validate_code_contract(self, conn, pid, record):
        contracted = {'specRef', 'entrypoint', 'modulePath', 'repository', 'commit', 'capabilities', 'checkEvidence'}
        supplied = contracted & set(record)
        if supplied and supplied != contracted:
            fail('A contracted implementation needs its full pinned spec, location and supplied checks.', details={'missing': sorted(contracted - supplied)})
        if not supplied:
            return
        spec = self._get(conn, record['specRef'], ['spec'])['record']
        if spec['status'] != 'ready' or spec['kind'] != record['kind']:
            fail('An implementation must bind a ready contract of the same code kind.')
        if set(record['capabilities']) != set(spec['capabilities']):
            fail('Implementation capabilities must match the pinned contract.')
        expected = {c['id'] for c in spec['acceptanceChecks']}
        actual = [c['checkId'] for c in record['checkEvidence']]
        if len(set(actual)) != len(actual) or set(actual) != expected:
            fail('Supply one explicit check result for every pinned acceptance check; do not claim unrun checks passed.')
        if ':' not in record['entrypoint'] or len(record['entrypoint'].split(':')) != 2:
            fail('Entrypoint must identify module-or-path:callable.')
        if record['commit'].casefold() in ('head', 'main', 'master', 'latest', 'unknown', 'uncommitted'):
            fail('Implementation must identify a fixed repository commit, not a moving or unknown revision.')
        identity = tuple(record[k] for k in ('repository', 'commit', 'modulePath', 'entrypoint'))
        for env in self._latest(conn, pid):
            other = env['record']
            if env['ref']['type'] == 'code' and other.get('specRef') and tuple(other.get(k) for k in ('repository', 'commit', 'modulePath', 'entrypoint')) == identity:
                fail('This implementation is already registered. Reuse its exact codeRef for another case or configuration.', 'duplicate_identity', {'existingRef': env['ref']})
        record['validationOrigin'] = 'supplied'

    def _validate_case_selection(self, conn, value):
        if value.get('datasetRef'):
            dataset = self._get(conn, value['datasetRef'], ['dataset'])['record']
            samples = value.get('sampleIds', [value['sampleId']] if value.get('sampleId') else [])
            if not set(samples) <= set(dataset['sampleIds']):
                fail('Selected samples must belong to the pinned dataset.')

    def _port_matches(self, port, envelope):
        value = envelope.get('effectiveRecord', envelope['record'])
        return (port['kind'] in (value.get('kind'), envelope['ref']['type'])
                and (not port.get('semantic') or port['semantic'] == value.get('semantic')))

    def _validate_contract_inputs(self, conn, spec, refs):
        if len({dump(ref) for ref in refs}) != len(refs):
            fail('Contract inputs must use unique exact references.')
        inputs = self._effective_many(conn, [self._get(conn, ref) for ref in refs])
        for port in spec['inputs']:
            matches = [env for env in inputs if self._port_matches(port, env)]
            if port.get('required', True) and not matches:
                fail('A required contract input is missing or incompatible.', details={'port': port['name']})
            if not port.get('multiple', True) and len(matches) > 1:
                fail('A contract input accepts only one record.', details={'port': port['name']})
        for env in inputs:
            if not any(self._port_matches(port, env) for port in spec['inputs']):
                fail('An input does not match a declared contract port.', details={'ref': env['ref']})

    def _validate_run_contract(self, conn, record):
        if record.get('sampleSelection'):
            self._validate_case_selection(conn, record['sampleSelection'])
        if not record.get('codeRef'):
            return
        code = self._get(conn, record['codeRef'], ['code'])['record']
        if not code.get('specRef'):
            return
        spec = self._get(conn, code['specRef'], ['spec'])['record']
        validate_schema(record['config'], spec['configSchema'], 'run.config')
        self._validate_contract_inputs(conn, spec, record['inputRefs'])
        if code['kind'] == 'inference' and not record.get('sampleSelection', {}).get('sampleIds'):
            fail('A contracted inference run declares its sampleSelection, including a single-case run.')

    def _validate_artifact_contract(self, conn, pid, record, exclude_ref=None):
        self._validate_case_selection(conn, record)
        if not record.get('producerRef'):
            return
        projected = self._effective(conn, self._get(conn, record['producerRef'], ['run']))
        run = projected.get('effectiveRecord', projected['record'])
        if not run.get('codeRef'):
            return
        code = self._get(conn, run['codeRef'], ['code'])['record']
        if not code.get('specRef'):
            return
        spec = self._get(conn, code['specRef'], ['spec'])['record']
        if not record.get('semantic'):
            fail('A contracted output needs an explicit semantic (for example final-image or clean-estimate).')
        # Per-output settings may differ from run defaults in a sweep, but the
        # actual settings still obey the same pinned method interface.
        validate_schema(record['config'], spec['configSchema'], 'artifact.config')
        envelope = {'ref': {'type': 'artifact'}, 'record': record}
        if not any(self._port_matches(port, envelope) for port in spec['outputs']):
            fail('Output kind/semantic does not match the pinned implementation contract.')
        selection = run.get('sampleSelection', {})
        if selection.get('sampleIds') and record.get('sampleId') not in selection['sampleIds']:
            fail('Output sampleId must belong to its actual producer selection.')
        if selection.get('datasetRef') != record.get('datasetRef'):
            fail('Output dataset identity must match its producer selection.')
        inputs = record.get('inputRefs', [])
        if any(ref not in run['inputRefs'] for ref in inputs):
            fail('Output inputRefs must be drawn from its actual producer inputs.')
        if record['semantic'] in ('clean-estimate', 'velocity-field') and not record.get('observation'):
            fail('Intermediate outputs need their observation step or time.')
        identity = (record['producerRef'], record.get('datasetRef'), record.get('sampleId'), record.get('taskKey'), record['semantic'], record.get('observation', {}), record['config'])
        for env in self._latest(conn, pid):
            if exclude_ref and env['ref'] == exclude_ref:
                continue
            other = env['record']
            if env['ref']['type'] != 'artifact':
                continue
            other_identity = (other.get('producerRef'), other.get('datasetRef'), other.get('sampleId'), other.get('taskKey'), other.get('semantic'), other.get('observation', {}), other.get('config', {}))
            if identity == other_identity:
                fail('This exact output identity already exists; reuse its artifactRef.', 'duplicate_identity', {'existingRef': env['ref']})

    def _status(self, record):
        if record.get('status') not in STATES:
            fail('Unsupported execution status.')

    def _check_dag(self, conn, pid, kind, record):
        rid = record.get('id')
        if not rid:
            return
        graph = {e['ref']['id']: [r['id'] for r in e['record'].get('parentRefs', [])] for e in self._latest(conn, pid) if e['ref']['type'] == kind}
        graph[rid] = [r['id'] for r in record.get('parentRefs', [])]
        active, done = set(), set()
        def visit(node):
            if node in active:
                fail('Research parent relations must not contain a cycle.')
            if node in done:
                return
            active.add(node)
            for parent in graph.get(node, []):
                visit(parent)
            active.remove(node)
            done.add(node)
        for node in graph:
            visit(node)

    def _result(self, result, metrics=None, sample_ids=None, conn=None):
        object_(result, 'typed result')
        kind = result.get('kind')
        if kind not in RESULT_KINDS:
            fail('Unsupported typed result kind; use an attachment for unparsed formats.')
        if result.get('sampleId') is not None and sample_ids is not None and result['sampleId'] not in sample_ids:
            fail('Result sampleId is not in the fixed input set.')
        if kind == 'metric':
            metric = result.get('metricId', result.get('name'))
            text(metric, 'metricId/name')
            value = result.get('value')
            if value is None:
                if result.get('status') not in ('missing', 'failed', 'undefined'):
                    fail('A nonnumeric metric needs an explicit missing/failed/undefined status.')
                text(result.get('reason'), 'metric reason')
            elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                fail('Metric value must be a finite number, or an explicit absent value.')
            elif result.get('status') in ('missing', 'failed', 'undefined'):
                fail('A missing/failed/undefined metric cannot also contain a numeric value.')
            if metrics is not None:
                if metric not in metrics:
                    fail('Metric is not defined in the selected protocol.')
                definition = metrics[metric]
                if 'unit' in result and result['unit'] != definition['unit']:
                    fail('Metric unit differs from the protocol.')
                directions = {'higher-is-better': 'higher', 'lower-is-better': 'lower'}
                if 'direction' in result and directions.get(result['direction'], result['direction']) != directions.get(definition['direction'], definition['direction']):
                    fail('Metric direction differs from the protocol.')
                if definition['granularity'] in ('dataset', 'aggregate') and result.get('sampleId'):
                    fail('Dataset-level metrics cannot be presented as single-sample values.')
                if definition['granularity'] == 'sample' and not result.get('sampleId') and not result.get('sampleIds'):
                    fail('Sample metrics need a sampleId or explicit aggregate sampleIds.')
                for bound in ('min', 'max'):
                    if value is not None and bound in definition and ((bound == 'min' and value < definition[bound]) or (bound == 'max' and value > definition[bound])):
                        fail('Metric is outside its declared range.')
            if 'sampleIds' in result:
                ids = array(result['sampleIds'], 'aggregate sampleIds')
                if len(ids) != len(set(ids)) or (sample_ids is not None and not set(ids) <= sample_ids):
                    fail('Aggregate sampleIds must be unique selected samples.')
                text(result.get('aggregation'), 'aggregation')
        elif kind == 'series':
            for axis in ('x', 'y'):
                obj = object_(result.get(axis + 'Axis', result.get(axis)), axis + ' axis')
                text(obj.get('label'), axis + '.label')
                text(obj.get('unit', ''), axis + '.unit', True)
            for point in array(result.get('points'), 'points'):
                values = [point.get('x'), point.get('y')] if isinstance(point, dict) else point
                if not isinstance(values, (list, tuple)) or len(values) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
                    fail('Series points must contain finite x and y values.')
        elif kind == 'image-set':
            for item in array(result.get('items'), 'image items'):
                object_(item, 'image item')
                if not item.get('artifactRef') and not item.get('uri'):
                    fail('An image item needs a fixed artifact reference or explicit URI.')
                if item.get('artifactRef'):
                    artifact = self._get(conn, item['artifactRef'], ['artifact'])['record']
                    if item.get('sampleId') is not None and artifact.get('sampleId') is not None and item['sampleId'] != artifact['sampleId']:
                        fail('Image item sampleId disagrees with its actual artifact.')
                if item.get('sampleId') is not None and sample_ids is not None and item['sampleId'] not in sample_ids:
                    fail('Image sample is not in the fixed inputs.')
        elif kind == 'table':
            columns = array(result.get('columns'), 'columns')
            keys = []
            for col in columns:
                object_(col, 'table column')
                key = col.get('key', col.get('name'))
                text(key, 'column.key/name')
                if col.get('type') not in ('string', 'number', 'boolean') or key in keys:
                    fail('Table columns need unique names and explicit types.')
                keys.append(key)
            for row in array(result.get('rows'), 'rows'):
                if not isinstance(row, dict) or set(row) - set(keys):
                    fail('Table rows must use declared column keys.')
                for col, key in zip(columns, keys):
                    value = row.get(key)
                    valid = value is None or (col['type'] == 'string' and isinstance(value, str)) or (col['type'] == 'boolean' and isinstance(value, bool)) or (col['type'] == 'number' and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value))
                    if not valid:
                        fail('Table cell does not match its declared type.')
        else:
            text(result.get('uri'), 'attachment.uri')
            text(result.get('mimeType', result.get('mediaType')), 'attachment.mimeType')

    def _context(self, conn, args):
        project = self._project(conn, args['projectId'])
        pid = project['id']
        research = self._get(conn, args['researchRef'], ['research'], pid) if args.get('researchRef') else None
        experiment = self._get(conn, args['experimentRef'], ['experiment'], pid) if args.get('experimentRef') else None
        if experiment:
            linked = self._get(conn, experiment['record']['researchRef'], ['research'], pid)
            if research and any(research['ref'][key] != linked['ref'][key] for key in ('projectId', 'type', 'id')):
                fail('Explicit research and experiment references do not match.')
            research = linked
        current_research = self._get(conn, {k: v for k, v in research['ref'].items() if k != 'version'}, ['research'], pid) if research else None
        current_research_summary = None
        research_version_notice = None
        if current_research:
            value = current_research['record']
            current_research_summary = {'ref': current_research['ref'], 'title': value['title'], 'kind': value['kind'], 'stage': value['stage'], 'hasHypothesis': bool(value.get('hypothesis')), 'judgment': value.get('judgment')}
            if current_research['ref'] != research['ref']:
                research_version_notice = '实验或所选记录基于研究 r%d；当前研究为 r%d。当前人工判断单独列出，原研究与项目基础绑定不变。' % (research['ref']['version'], current_research['ref']['version'])
        records = self._effective_many(conn, self._latest(conn, pid))
        # Context is a present-day reading view. Exact source documents remain
        # available from record_get and frozen report snapshots.
        records = [dict(env, record=env.get('effectiveRecord', env['record'])) for env in records]
        # Keep purpose declarations distinct from completed execution facts. A
        # selected experiment may retain an older research revision; expose its
        # declarations alongside the current revision without repinning either.
        declared_research = ([research] if research else [e for e in records if e['ref']['type'] == 'research'])
        if current_research and current_research['ref'] != research['ref']:
            declared_research.append(current_research)
        declared_implementations = []
        declaration_count = sum(len(e['record'].get('implementationLinks', [])) for e in declared_research)
        role_names = {'implementation': '研究实现', 'control': '对照', 'diagnostic': '诊断'}
        # Interleave revisions/questions so one full declaration list cannot
        # hide all declarations from the current revision or another question.
        max_links = max((len(e['record'].get('implementationLinks', [])) for e in declared_research), default=0)
        for index in range(max_links):
            for envelope in declared_research:
                links = envelope['record'].get('implementationLinks', [])
                if index >= len(links):
                    continue
                link = links[index]
                target = self._get(conn, link['targetRef'], ['spec', 'code'])
                declaration = {'researchRef': envelope['ref'], 'researchTitle': envelope['record']['title'][:180],
                               'targetRef': target['ref'], 'title': target['record']['title'][:180],
                               'role': link['role'], 'roleLabel': role_names[link['role']], 'intentOnly': True,
                               'researchVersionRole': 'current' if not research or envelope['ref'] == current_research['ref'] else 'bound'}
                if link.get('note'):
                    declaration['note'] = link['note'][:200]
                declared_implementations.append(declaration)
                if len(declared_implementations) >= 32:
                    break
            if len(declared_implementations) >= 32:
                break
        selected = [self._get(conn, r) for r in array(args.get('selectionRefs', []), 'selectionRefs')]
        relevant = records
        if experiment:
            eid = experiment['ref']['id']
            relevant = [e for e in records if any(r['projectId'] == pid and r['type'] == 'experiment' and r['id'] == eid for r in self._walk_refs(e['record']))]
        elif research:
            rid = research['ref']['id']
            experiment_ids = {e['ref']['id'] for e in records if e['ref']['type'] == 'experiment' and e['record']['researchRef']['id'] == rid}
            relevant = [e for e in records if any(r['projectId'] == pid and ((r['type'] == 'research' and r['id'] == rid) or (r['type'] == 'experiment' and r['id'] in experiment_ids)) for r in self._walk_refs(e['record']))]
        relevant = [e for e in relevant if not (e['ref']['type'] == 'usage' and e['record'].get('revoked'))]
        relevant = [e for e in relevant if e['ref']['type'] != 'amendment' or e['record'].get('status') == 'pending']
        completed, pending = [], []
        for env in relevant:
            r, ref = env['record'], env['ref']
            if ref['type'] == 'amendment':
                pending.append({'ref': ref, 'title': r['title'], 'reason': '来源修正建议等待人工审阅；原始记录尚未改变。', 'requiresHuman': True})
            if ref['type'] in ('run', 'evaluation'):
                status = r.get('status')
                fact = {'ref': ref, 'title': r.get('title', ref['id']), 'status': status}
                if r.get('recoveredByRef'):
                    completed.append(dict(fact, status='recovered', originalStatus=status, recoveredByRef=r['recoveredByRef']))
                elif status == 'completed':
                    completed.append(fact)
                elif status in ('planned', 'running', 'failed', 'partial'):
                    pending.append(dict(fact, reason={'planned': '已登记待执行', 'running': '等待已有执行结果', 'failed': '失败记录待检查', 'partial': '部分完成，需核对覆盖范围'}[status]))
        usages = [e for e in relevant if e['ref']['type'] == 'usage' and not e['record'].get('revoked')]
        if experiment and not usages:
            pending.append({'ref': experiment['ref'], 'reason': '当前实验尚未选择实际材料；不自动复用其他研究的结果。'})
        if not research:
            suggested = [{'label': '选择或登记研究问题', 'reason': '先确定这次要解决的具体问题；开放探索可以没有假设。', 'operation': 'rws_research_save'}]
        elif not experiment:
            suggested = [{'label': '准备实验或分析', 'reason': '围绕当前问题选择操作与已有材料，由人决定下一步。', 'operation': 'rws_experiment_save', 'targetRef': research['ref']}]
        elif not usages:
            suggested = [{'label': '选择已有材料', 'reason': '明确实际产物及用途后再进行比较。', 'operation': 'rws_usage_save', 'targetRef': experiment['ref']}]
        else:
            suggested = [{'label': '检查证据并记录分析', 'reason': '来源和条件明确后，再解释现象及局限；完成运行不等于假设成立。', 'operation': 'rws_analysis_save', 'targetRef': experiment['ref']}]
        pending_amendment = next((e for e in relevant if e['ref']['type'] == 'amendment'), None)
        if pending_amendment:
            suggested.insert(0, {'label': '审阅来源修正建议', 'reason': '只有人工确认才应用来源修正；执行和科学结论不会自动改变。', 'operation': 'rws_amendment_apply', 'targetRef': pending_amendment['ref'], 'requiresHuman': True, 'reviewUrl': '/?' + urlencode({'projectId': pid, 'amendments': '1'})})
        foundation_rev = experiment['record']['foundationRevision'] if experiment else project['versions'][-1]['revision']
        foundation = next(v for v in project['versions'] if v['revision'] == foundation_rev)
        if experiment and experiment['record'].get('protocolRef') and research['record'].get('kind') != 'exploration':
            protocol_ref = experiment['record']['protocolRef']
            required = {dump(ref): ref for usage in usages for ref in usage['record']['artifactRefs']}
            evaluated = set()
            for envelope in records:
                evaluation = envelope['record']
                if envelope['ref']['type'] == 'evaluation' and evaluation.get('status') == 'completed' and evaluation.get('protocolRef') == protocol_ref:
                    evaluated.update(dump(ref) for ref in evaluation.get('inputRefs', []))
            for key, ref in required.items():
                if key not in evaluated:
                    pending.append({'ref': ref, 'protocolRef': protocol_ref, 'reason': '已选材料尚无匹配此协议及版本的完成评估。'})
        candidates = ([research] if research else []) + ([current_research] if current_research else []) + ([experiment] if experiment else []) + selected + relevant
        candidates += self._closure(conn, [e['record'] for e in candidates])
        unique = {}
        explicitly_selected = {dump(e['ref']) for e in selected}
        for envelope in candidates:
            ref, value = envelope['ref'], envelope['record']
            if ref['type'] == 'usage' and value.get('revoked'):
                continue
            if ref['type'] == 'amendment' and value.get('status') != 'pending' and dump(ref) not in explicitly_selected:
                continue
            summary = {'ref': ref, 'title': str(value.get('title', value.get('label', ref['id'])))[:180]}
            for field in ('kind', 'status', 'codeRef', 'producerRef', 'experimentRef', 'researchRef', 'sampleId', 'availability', 'provenance', 'specRef', 'semantic', 'observation', 'datasetRef', 'taskKey', 'sampleSelection', 'purpose', 'recoveredByRef'):
                if field in value:
                    summary[field] = value[field]
            summary['sourceProjectId'] = ref['projectId']
            unique[dump(ref)] = summary
        object_values = list(unique.values())
        # A large gallery or audit trail must not consume the entire context
        # budget. Keep selected objects first, then represent each object kind.
        priority = ([research] if research else []) + ([current_research] if current_research else []) + ([experiment] if experiment else []) + selected
        priority_keys = list(dict.fromkeys(dump(e['ref']) for e in priority))
        objects = [unique[key] for key in priority_keys if key in unique][:40]
        chosen = {dump(item['ref']) for item in objects}
        buckets = {}
        for item in object_values:
            if dump(item['ref']) not in chosen:
                buckets.setdefault(item['ref']['type'], []).append(item)
        order = ('research', 'experiment', 'amendment', 'spec', 'code', 'run', 'artifact', 'protocol', 'dataset', 'comparison', 'evaluation', 'analysis', 'report', 'conversation', 'usage', 'proposal')
        index = 0
        while len(objects) < min(40, len(object_values)):
            for kind in order:
                if index < len(buckets.get(kind, [])) and len(objects) < 40:
                    objects.append(buckets[kind][index])
            index += 1
        return {'projectId': pid, 'projectName': project['name'], 'revision': project['revision'], 'foundation': foundation, 'latestFoundationRevision': project['versions'][-1]['revision'], 'position': {'researchRef': research['ref'] if research else None, 'experimentRef': experiment['ref'] if experiment else None, 'stage': research['record']['stage'] if research else None, 'activeStages': project['activeStages']}, 'currentResearchRef': current_research['ref'] if current_research else None, 'currentResearch': current_research_summary, 'researchVersionNotice': research_version_notice, 'declaredImplementations': declared_implementations, 'declaredImplementationCount': declaration_count, 'declaredImplementationsTruncated': declaration_count > len(declared_implementations), 'objects': objects, 'objectCount': len(object_values), 'objectsTruncated': len(object_values) > len(objects), 'readMore': {'operation': 'rws_record_get', 'note': '按精确ref读取完整记录；对象摘要不替代执行输入。'}, 'completed': completed, 'pending': pending, 'suggestedActions': suggested, 'notice': '仅依据已登记记录；用途关联不是执行或完成证据，建议不授权执行。项目基础与阶段变更需人工确认。'}
