import type { GameCreationInput } from '@/api/games';

// 封面用地形色点出玩法特征；具体地块贴图在接入棋盘时按同一组色值使用。
const coverTerrains = [
  { key: 'field', name: '麦田', tone: '#dcc069' },
  { key: 'forest', name: '森林', tone: '#6f9f57' },
  { key: 'lake', name: '湖泊', tone: '#6ba7c9' },
  { key: 'meadow', name: '草地', tone: '#abd06f' },
];

export function KingdominoCover() {
  return (
    <div className="game-mini-tiles">
      {coverTerrains.map((terrain) => (
        <span
          key={terrain.key}
          className="game-mini-tile"
          style={{ background: terrain.tone }}
          aria-hidden="true"
        />
      ))}
    </div>
  );
}

export const kingdominoPresentation = {
  Cover: KingdominoCover,
  description: '2～4 人拼放 5×5 王国，按「地形格数 × 皇冠数」计分。',
  rules:
    '2～4 人共用国王线。放王阶段每人把国王放到自己选定的地块上；之后按国王线编号升序行动：先把自己国王所在的地块放进王国，再挑一张新线地块放上国王。相邻格地形必须一致，起始地块视为万能地块。5×5 边界同时生效，放不下时必须弃置该地块。全部地块用完后，每座王国按每种地形的「格数 × 皇冠数」求和计分，总分最高者获胜。',
  createInput: (): GameCreationInput => ({
    game_type: 'kingdomino',
    ruleset_id: 'kingdomino.classic',
    ruleset_version: 1,
    initial_seat_id: 'pink',
    config: {},
  }),
};
