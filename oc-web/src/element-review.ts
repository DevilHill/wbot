import type { ElementResolution, ElementReview } from './element-types';

export type ConflictChoice = 'main' | 'source';
export type ConflictChoices = Record<string, ConflictChoice>;
export const conflictKey = (id: string, field: string) => JSON.stringify([id, field]);

export function reviewedResolutions(review: ElementReview, choices: ConflictChoices): ElementResolution[] {
  return review.conflicts.map(conflict => {
    const choice = choices[conflictKey(conflict.id, conflict.field)];
    if (choice !== 'main' && choice !== 'source') throw new Error('请逐项处理全部冲突后再合并');
    return { id: conflict.id, field: conflict.field, value: conflict[choice] };
  });
}

export function canMergeElements(review: ElementReview, choices: ConflictChoices) {
  return review.request.state === 'open' && review.conflicts.every(conflict => choices[conflictKey(conflict.id, conflict.field)] !== undefined);
}

export type MutationIntent = { signature: string; id: string };
export function intentFor(previous: MutationIntent | null, payload: unknown): MutationIntent {
  const signature = JSON.stringify(payload);
  return previous?.signature === signature ? previous : { signature, id: crypto.randomUUID() };
}
