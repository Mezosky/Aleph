declare module 'plotly.js-basic-dist-min' {
  import type * as PlotlyType from 'plotly.js'

  const Plotly: typeof PlotlyType
  export default Plotly
}

declare module 'umap-js' {
  export interface UMAPParameters {
    nComponents?: number
    nNeighbors?: number
    minDist?: number
    spread?: number
    random?: () => number
  }

  export class UMAP {
    constructor(parameters?: UMAPParameters)
    fit(data: number[][]): number[][]
  }
}
