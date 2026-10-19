import type { ComponentType } from 'react';
import type { GameCreationInput } from '@/api/games';
import { Board as GomokuBoard } from '@/scenes/games/gomoku/Board';
import { gomokuPresentation } from '@/scenes/games/gomoku/presentation';
import { Board as AeroplaneBoard } from '@/scenes/games/aeroplane/Board';
import { aeroplanePresentation } from '@/scenes/games/aeroplane/presentation';
import { Board as KingdominoBoard } from '@/scenes/games/kingdomino/Board';
import { kingdominoPresentation } from '@/scenes/games/kingdomino/presentation';
import type { BoardProps } from './presentation';

// 场景注册契约：大厅与房间页用封面、说明、规则与创建参数，
// 对局页用棋盘；未注册的玩法在这两处都会被识别为不可用。
export type GameScene = {
  Cover: ComponentType;
  description: string;
  rules: string;
  createInput: () => GameCreationInput;
  Board: ComponentType<BoardProps>;
};

const gameScenes: Partial<Record<string, GameScene>> = {
  gomoku: { ...gomokuPresentation, Board: GomokuBoard },
  aeroplane: { ...aeroplanePresentation, Board: AeroplaneBoard },
  kingdomino: { ...kingdominoPresentation, Board: KingdominoBoard },
};

export function gameSceneFor(gameType: string): GameScene | undefined {
  return gameScenes[gameType];
}
