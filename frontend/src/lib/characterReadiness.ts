import type { SchemaOf } from '@/api/http';

type Character = SchemaOf<'CharacterView'>;

export function canCharacterChat(character: Character): boolean {
  return character.availability_status === 'available' && character.memory_status === 'ready';
}

export function characterStatusText(character: Character): string {
  if (character.memory_status === 'preparing') return '记忆准备中';
  if (character.memory_status === 'failed') return '记忆准备失败';
  return canCharacterChat(character) ? '可参与对话' : '暂不可用';
}

export function characterPreparationError(character: Character): string {
  switch (character.memory_error_code) {
    case 'material_preparation_failed': return '作者材料处理失败，请重新准备。';
    case 'author_organization_failed': return '长期记忆整理失败，请检查后端任务记录后重新准备。';
    case 'author_material_budget_exceeded': return '作者材料超出处理限额，请检查后端任务记录。';
    default: return '记忆准备未完成，请检查后端任务记录后重新准备。';
  }
}
