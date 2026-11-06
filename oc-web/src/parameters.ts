import type { ParameterDefinition, Parameters } from './types.ts';

export function initialParameterValues(definitions: Record<string, ParameterDefinition>, defaults: Parameters = {}) {
  return Object.fromEntries(Object.entries(definitions).map(([name, definition]) => {
    const value = defaults[name] ?? definition.default;
    return [name, value === undefined ? '' : String(value)];
  }));
}

export function parseParameterValues(definitions: Record<string, ParameterDefinition>, inputs: Record<string, string>): Parameters {
  const parameters: Parameters = {};
  for (const [name, definition] of Object.entries(definitions)) {
    const value = inputs[name] ?? '';
    if (value === '' && definition.type !== 'string') {
      if (definition.required && definition.default === undefined) throw new Error(`请填写 ${name}`);
      continue;
    }
    if (definition.type === 'string') {
      parameters[name] = value;
    } else if (definition.type === 'boolean') {
      if (!['true', 'false'].includes(value)) throw new Error(`${name} 必须是布尔值`);
      parameters[name] = value === 'true';
    } else {
      const number = Number(value);
      if (!Number.isFinite(number)) throw new Error(`${name} 必须是有限数值`);
      if (definition.type === 'integer' && !Number.isInteger(number)) throw new Error(`${name} 必须是整数`);
      parameters[name] = number;
    }
  }
  return parameters;
}
