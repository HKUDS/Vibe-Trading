
/*
* Licensed to the Apache Software Foundation (ASF) under one
* or more contributor license agreements.  See the NOTICE file
* distributed with this work for additional information
* regarding copyright ownership.  The ASF licenses this file
* to you under the Apache License, Version 2.0 (the
* "License"); you may not use this file except in compliance
* with the License.  You may obtain a copy of the License at
*
*   http://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing,
* software distributed under the License is distributed on an
* "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
* KIND, either express or implied.  See the License for the
* specific language governing permissions and limitations
* under the License.
*/


/**
 * AUTO-GENERATED FILE. DO NOT MODIFY.
 */

/*
* Licensed to the Apache Software Foundation (ASF) under one
* or more contributor license agreements.  See the NOTICE file
* distributed with this work for additional information
* regarding copyright ownership.  The ASF licenses this file
* to you under the Apache License, Version 2.0 (the
* "License"); you may not use this file except in compliance
* with the License.  You may obtain a copy of the License at
*
*   http://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing,
* software distributed under the License is distributed on an
* "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
* KIND, either express or implied.  See the License for the
* specific language governing permissions and limitations
* under the License.
*/
import { getLayoutRect } from '../../util/layout.js';
import { ListIterator } from '../../util/model.js';
import { eqNaN, isArray, retrieve2 } from 'zrender/lib/core/util.js';
import { WH, XY } from '../../util/graphic.js';
import Model from '../../model/Model.js';
import { mathMax, mathMin, parsePositionSizeOption } from '../../util/number.js';
import { createNaNRectLike, MatrixClampOption, MatrixCellLayoutInfoType, parseCoordRangeOption, resetXYLocatorRange, xyLocatorRangeToRectOneDim } from './matrixCoordHelper.js';
import { error } from '../../util/log.js';
import { injectCoordSysByOption, simpleCoordSysInjectionProvider } from '../../core/CoordinateSystem.js';
var Matrix = /** @class */function () {
  function Matrix(matrixModel, ecModel, api) {
    this.dimensions = Matrix.dimensions;
    this.type = 'matrix';
    this._model = matrixModel;
    var models = this._dimModels = {
      x: matrixModel.getDimensionModel('x'),
      y: matrixModel.getDimensionModel('y')
    };
    this._dims = {
      x: models.x.dim,
      y: models.y.dim
    };
    this._resize(matrixModel, api);
  }
  /**
   * @see fetchers in `model/referHelper.ts`,
   * which is used to parse data in ordinal way.
   * In most series only 'x' and 'y' is required,
   * but some series, such as heatmap, can specify value.
   */
  Matrix.getDimensionsInfo = function () {
    return [{
      name: 'x',
      type: 'ordinal'
    }, {
      name: 'y',
      type: 'ordinal'
    }, {
      name: 'value'
    }];
  };
  Matrix.create = function (ecModel, api) {
    var matrixList = [];
    ecModel.eachComponent('matrix', function (matrixModel) {
      var matrix = new Matrix(matrixModel, ecModel, api);
      matrixList.push(matrix);
      matrixModel.coordinateSystem = matrix;
    });
    // Inject coordinate system
    // PENDING: optimize to not to travel all components?
    //  (collect relevant components in ecModel only when model update?)
    ecModel.eachComponent(function (mainType, componentModel) {
      injectCoordSysByOption({
        targetModel: componentModel,
        coordSysType: 'matrix',
        coordSysProvider: simpleCoordSysInjectionProvider
      });
    });
    return matrixList;
  };
  Matrix.prototype.getRect = function () {
    return this._rect;
  };
  Matrix.prototype._resize = function (matrixModel, api) {
    var dims = this._dims;
    var dimModels = this._dimModels;
    var rect = this._rect = getLayoutRect(matrixModel.getBoxLayoutParams(), {
      width: api.getWidth(),
      height: api.getHeight()
    });
    layOutUnitsOnDimension(dimModels, dims, rect, 0);
    layOutUnitsOnDimension(dimModels, dims, rect, 1);
    layOutDimCellsRestInfoByUnit(0, dims);
    layOutDimCellsRestInfoByUnit(1, dims);
    layOutBodyCornerCellMerge(this._model.getBody(), dims);
    layOutBodyCornerCellMerge(this._model.getCorner(), dims);
  };
  /**
   * @implement
   * - The input is allowed to be `[NaN/null/undefined, xxx]`/`[xxx, NaN/null/undefined]`;
   *  the return is `[NaN, xxxresult]`/`[xxxresult, NaN]` or clamped boundary value if
   *  `clamp` passed. This is for the usage that only get coord on single x or y.
   * - Alwasy return an numeric array, but never be null/undefined.
   *  If it can not be located or invalid, return `[NaN, NaN]`.
   */
  Matrix.prototype.dataToPoint = function (data, opt, out) {
    out = out || [];
    this.dataToLayout(data, opt, _dtpOutDataToLayout);
    out[0] = _dtpOutDataToLayout.rect.x + _dtpOutDataToLayout.rect.width / 2;
    out[1] = _dtpOutDataToLayout.rect.y + _dtpOutDataToLayout.rect.height / 2;
    return out;
  };
  /**
   * @implement
   * - The input is allowed to be `[NaN/null/undefined, xxx]`/`[xxx, NaN/null/undefined]`;
   *  the return is `{x: NaN, width: NaN, y: xxxresulty, height: xxxresulth}`/
   *  `{y: NaN, height: NaN, x: xxxresultx, width: xxxresultw}` or clamped boundary value
   *  if `clamp` passed. This is for the usage that only get coord on single x or y.
   * - The returned `out.rect` and `out.matrixXYLocatorRange` is always an object or an 2d-array,
   *  but never be null/undefined. If it cannot be located or invalid, `NaN` is in their
   *  corresponding number props.
   * - Do not provide `out.contentRect`, because it's allowed to input non-leaf dimension x/y or
   *  a range of x/y, which determines a rect covering multiple cells (even not merged), in which
   *  case the padding and borderWidth can not be determined to make a contentRect. Therefore only
   *  return `out.rect` in any case for consistency. The caller is responsible for adding space to
   *  avoid covering cell borders, if necessary.
   */
  Matrix.prototype.dataToLayout = function (data, opt, out) {
    var dims = this._dims;
    out = out || {};
    var outRect = out.rect = out.rect || {};
    outRect.x = outRect.y = outRect.width = outRect.height = NaN;
    var outLocRange = out.matrixXYLocatorRange = resetXYLocatorRange(out.matrixXYLocatorRange);
    if (!isArray(data)) {
      if (process.env.NODE_ENV !== 'production') {
        error('Input data must be an array in `convertToLayout`, `convertToPixel`');
      }
      return out;
    }
    parseCoordRangeOption(outLocRange, null, data, dims, retrieve2(opt && opt.clamp, MatrixClampOption.none));
    if (!opt || !opt.ignoreMergeCells) {
      if (!opt || opt.clamp !== MatrixClampOption.corner) {
        this._model.getBody().expandRangeByCellMerge(outLocRange);
      }
      if (!opt || opt.clamp !== MatrixClampOption.body) {
        this._model.getCorner().expandRangeByCellMerge(outLocRange);
      }
    }
    xyLocatorRangeToRectOneDim(outRect, outLocRange, dims, 0);
    xyLocatorRangeToRectOneDim(outRect, outLocRange, dims, 1);
    return out;
  };
  /**
   * The returned locator pair can be the input of `dataToPoint` or `dataToLayout`.
   *
   * If point[0] is out of the matrix rect,
   *  the out[0] is NaN;
   * else if it is on the right of top-left corner of body,
   *  the out[0] is the oridinal number (>= 0).
   * else
   *  out[0] is the locator for corner or header (<= 0).
   *
   * The same rule goes for point[1] and out[1].
   *
   * But point[0] and point[1] are calculated separately, i.e.,
   * the reuslt can be `[1, NaN]` or `[NaN, 1]` if only one dimension is out of boundary.
   *
   * @implement
   */
  Matrix.prototype.pointToData = function (point, opt, out) {
    var dims = this._dims;
    pointToDataOneDimPrepareCtx(_tmpCtxPointToData, 0, dims, point, opt && opt.clamp);
    pointToDataOneDimPrepareCtx(_tmpCtxPointToData, 1, dims, point, opt && opt.clamp);
    out = out || [];
    out[0] = out[1] = NaN;
    if (_tmpCtxPointToData.y === CtxPointToDataAreaType.inCorner && _tmpCtxPointToData.x === CtxPointToDataAreaType.inBody) {
      pointToDataOnlyHeaderFillOut(_tmpCtxPointToData, out, 0, dims);
    } else if (_tmpCtxPointToData.x === CtxPointToDataAreaType.inCorner && _tmpCtxPointToData.y === CtxPointToDataAreaType.inBody) {
      pointToDataOnlyHeaderFillOut(_tmpCtxPointToData, out, 1, dims);
    } else {
      pointToDataBodyCornerFillOut(_tmpCtxPointToData, out, 0, dims);
      pointToDataBodyCornerFillOut(_tmpCtxPointToData, out, 1, dims);
    }
    return out;
  };
  Matrix.prototype.convertToPixel = function (ecModel, finder, value, opt) {
    var coordSys = getCoordSys(finder);
    return coordSys === this ? coordSys.dataToPoint(value, opt) : undefined;
  };
  Matrix.prototype.convertToLayout = function (ecModel, finder, value, opt) {
    var coordSys = getCoordSys(finder);
    return coordSys === this ? coordSys.dataToLayout(value, opt) : undefined;
  };
  Matrix.prototype.convertFromPixel = function (ecModel, finder, pixel, opt) {
    var coordSys = getCoordSys(finder);
    return coordSys === this ? coordSys.pointToData(pixel, opt) : undefined;
  };
  Matrix.prototype.containPoint = function (point) {
    return this._rect.contain(point[0], point[1]);
  };
  Matrix.dimensions = ['x', 'y', 'value'];
  return Matrix;
}();
var _dtpOutDataToLayout = {
  rect: createNaNRectLike()
};
var _ptdLevelIt = new ListIterator();
var _ptdDimCellIt = new ListIterator();
function layOutUnitsOnDimension(dimModels, dims, matrixRect, dimIdx) {
  var otherDimIdx = 1 - dimIdx;
  var thisDim = dims[XY[dimIdx]];
  var otherDim = dims[XY[otherDimIdx]];
  // Notice: If matrix.x/y.show is false, still lay out, to ensure the
  // consistent return of `dataToLayout`.
  var otherDimShow = otherDim.shouldShow();
  // Reset
  for (var it_1 = thisDim.resetCellIterator(); it_1.next();) {
    it_1.item.wh = it_1.item.xy = NaN;
  }
  for (var it_2 = otherDim.resetLayoutIterator(null, dimIdx); it_2.next();) {
    it_2.item.wh = it_2.item.xy = NaN;
  }
  // Set specified size from option.
  var restSize = matrixRect[WH[dimIdx]];
  var restCellsCount = thisDim.getLocatorCount(dimIdx) + otherDim.getLocatorCount(dimIdx);
  var tmpLevelModel = new Model();
  for (var it_3 = otherDim.resetLevelIterator(); it_3.next();) {
    // Consider `matrix.x.levelSize` and `matrix.x.levels[i].levelSize`.
    tmpLevelModel.option = it_3.item.option;
    tmpLevelModel.parentModel = dimModels[XY[otherDimIdx]];
    layOutSpecified(it_3.item, otherDimShow ? tmpLevelModel.get('levelSize') : 0);
  }
  var tmpCellModel = new Model();
  for (var it_4 = thisDim.resetCellIterator(); it_4.next();) {
    // Only leaf support size specification, to avoid unnecessary complexity.
    if (it_4.item.type === MatrixCellLayoutInfoType.leaf) {
      tmpCellModel.option = it_4.item.option;
      tmpCellModel.parentModel = undefined;
      layOutSpecified(it_4.item, tmpCellModel.get('size'));
    }
  }
  function layOutSpecified(item, sizeOption) {
    var size = parseSizeOption(sizeOption, dimIdx, matrixRect);
    if (!eqNaN(size)) {
      item.wh = confineSize(size, restSize);
      restSize = confineSize(restSize - item.wh);
      restCellsCount--;
    }
  }
  // Set all sizes and positions to levels and leaf cells of which size is unspecified.
  // Contents lay out based on matrix, rather than inverse; therefore do not support
  // calculating size based on content, but allocate equally.
  var computedCellWH = restCellsCount ? restSize / restCellsCount : 0;
  // If all size specified, but some space remain (may also caused by matrix.x/y.show: false)
  // do not align to the big most edge.
  var notAlignToBigmost = !restCellsCount && restSize >= 1; // `1` for cumulative precision error.
  var currXY = matrixRect[XY[dimIdx]];
  var maxLocator = thisDim.getLocatorCount(dimIdx) - 1;
  var it = new ListIterator();
  // Lay out levels of the perpendicular dim.
  for (otherDim.resetLayoutIterator(it, dimIdx); it.next();) {
    layOutUnspecified(it.item);
  }
  for (thisDim.resetLayoutIterator(it, dimIdx); it.next();) {
    layOutUnspecified(it.item);
  }
  function layOutUnspecified(item) {
    if (eqNaN(item.wh)) {
      item.wh = computedCellWH;
    }
    item.xy = currXY;
    if (item.id[XY[dimIdx]] === maxLocator && !notAlignToBigmost) {
      // Align to the rightmost border, consider cumulative precision error.
      item.wh = matrixRect[XY[dimIdx]] + matrixRect[WH[dimIdx]] - item.xy;
    }
    currXY += item.wh;
  }
}
function layOutDimCellsRestInfoByUnit(dimIdx, dims) {
  // Finally save layout info based on the unit leaves and levels.
  for (var it_5 = dims[XY[dimIdx]].resetCellIterator(); it_5.next();) {
    var dimCell = it_5.item;
    layOutRectOneDimBasedOnUnit(dimCell.rect, dimIdx, dimCell.id, dimCell.span, dims);
    // Consider level varitation on tree leaves, should extend the size to touch matrix body
    // to avoid weird appearance.
    layOutRectOneDimBasedOnUnit(dimCell.rect, 1 - dimIdx, dimCell.id, dimCell.span, dims);
    if (dimCell.type === MatrixCellLayoutInfoType.nonLeaf) {
      // `xy` and `wh` need to be saved in non-leaf since it supports locating by non-leaf
      // in `dataToPoint` or `dataToLayout`.
      dimCell.xy = dimCell.rect[XY[dimIdx]];
      dimCell.wh = dimCell.rect[WH[dimIdx]];
    }
  }
}
function layOutBodyCornerCellMerge(bodyOrCorner, dims) {
  bodyOrCorner.travelExistingCells(function (cell) {
    var computedSpan = cell.span;
    if (computedSpan) {
      var layoutRect = cell.spanRect;
      var id = cell.id;
      layOutRectOneDimBasedOnUnit(layoutRect, 0, id, computedSpan, dims);
      layOutRectOneDimBasedOnUnit(layoutRect, 1, id, computedSpan, dims);
    }
  });
}
// Save to rect for rendering.
function layOutRectOneDimBasedOnUnit(outRect, dimIdx, id, span, dims) {
  outRect[WH[dimIdx]] = 0;
  var locator = id[XY[dimIdx]];
  var dim = locator < 0 ? dims[XY[1 - dimIdx]] : dims[XY[dimIdx]];
  var layoutUnit = dim.getUnitLayoutInfo(dimIdx, id[XY[dimIdx]]);
  outRect[XY[dimIdx]] = layoutUnit.xy;
  outRect[WH[dimIdx]] = layoutUnit.wh;
  if (span[XY[dimIdx]] > 1) {
    var layoutUnit2 = dim.getUnitLayoutInfo(dimIdx, id[XY[dimIdx]] + span[XY[dimIdx]] - 1);
    // Be careful the cumulative error - cell must be aligned.
    outRect[WH[dimIdx]] = layoutUnit2.xy + layoutUnit2.wh - layoutUnit.xy;
  }
}
/**
 * Return NaN if not defined or invalid.
 */
function parseSizeOption(sizeOption, dimIdx, matrixRect) {
  var sizeNum = parsePositionSizeOption(sizeOption, matrixRect[WH[dimIdx]]);
  return confineSize(sizeNum, matrixRect[WH[dimIdx]]);
}
function confineSize(sizeNum, sizeLimit) {
  return Math.max(Math.min(sizeNum, retrieve2(sizeLimit, Infinity)), 0);
}
function getCoordSys(finder) {
  var matrixModel = finder.matrixModel;
  var seriesModel = finder.seriesModel;
  var coordSys = matrixModel ? matrixModel.coordinateSystem : seriesModel ? seriesModel.coordinateSystem : null;
  return coordSys;
}
var CtxPointToDataAreaType = {
  inBody: 1,
  inCorner: 2,
  outside: 3
};
// For quick performance optimization in pointToData.
var _tmpCtxPointToData = {
  x: null,
  y: null,
  point: []
};
function pointToDataOneDimPrepareCtx(ctx, dimIdx, dims, point, clamp) {
  var thisDim = dims[XY[dimIdx]];
  var otherDim = dims[XY[1 - dimIdx]];
  // Notice: considered cases: `matrix.x/y.show: false`, `matrix.x/y.data` is empty.
  // In this cases the `layout.xy` is on the edge and `layout.wh` is `0`; they still can be
  // use to calculate clampping.
  var bodyMaxUnit = thisDim.getUnitLayoutInfo(dimIdx, thisDim.getLocatorCount(dimIdx) - 1);
  var body0Unit = thisDim.getUnitLayoutInfo(dimIdx, 0);
  var cornerMinUnit = otherDim.getUnitLayoutInfo(dimIdx, -otherDim.getLocatorCount(dimIdx));
  var cornerMinus1Unit = otherDim.shouldShow() ? otherDim.getUnitLayoutInfo(dimIdx, -1) : null;
  var coord = ctx.point[dimIdx] = point[dimIdx]; // Transfer the oridinal coord.
  if (!body0Unit && !cornerMinus1Unit) {
    ctx[XY[dimIdx]] = CtxPointToDataAreaType.outside;
    return;
  }
  if (clamp === MatrixClampOption.body) {
    if (body0Unit) {
      ctx[XY[dimIdx]] = CtxPointToDataAreaType.inBody;
      coord = mathMin(bodyMaxUnit.xy + bodyMaxUnit.wh, mathMax(body0Unit.xy, coord));
      ctx.point[dimIdx] = coord;
    } else {
      // If clamp to body, the result must not be in header.
      ctx[XY[dimIdx]] = CtxPointToDataAreaType.outside;
    }
    return;
  } else if (clamp === MatrixClampOption.corner) {
    if (cornerMinus1Unit) {
      ctx[XY[dimIdx]] = CtxPointToDataAreaType.inCorner;
      coord = mathMin(cornerMinus1Unit.xy + cornerMinus1Unit.wh, mathMax(cornerMinUnit.xy, coord));
      ctx.point[dimIdx] = coord;
    } else {
      // If clamp to corner, the result must not be in body.
      ctx[XY[dimIdx]] = CtxPointToDataAreaType.outside;
    }
    return;
  }
  var pxLoc0 = body0Unit ? body0Unit.xy : cornerMinus1Unit ? cornerMinus1Unit.xy + cornerMinus1Unit.wh : NaN;
  var pxMin = cornerMinUnit ? cornerMinUnit.xy : pxLoc0;
  var pxMax = bodyMaxUnit ? bodyMaxUnit.xy + bodyMaxUnit.wh : pxLoc0;
  if (coord < pxMin) {
    if (!clamp) {
      // Quick pass for later calc, since mouse event on any place will enter this method if use `pointToData`.
      ctx[XY[dimIdx]] = CtxPointToDataAreaType.outside;
      return;
    }
    coord = pxMin;
  } else if (coord > pxMax) {
    if (!clamp) {
      ctx[XY[dimIdx]] = CtxPointToDataAreaType.outside;
      return;
    }
    coord = pxMax;
  }
  ctx.point[dimIdx] = coord; // Save the updated coord.
  ctx[XY[dimIdx]] = pxLoc0 <= coord && coord <= pxMax ? CtxPointToDataAreaType.inBody : pxMin <= coord && coord <= pxLoc0 ? CtxPointToDataAreaType.inCorner : CtxPointToDataAreaType.outside;
  // Every props in ctx must be set in every branch of this method.
}
// Assume partialOut has been set to NaN outside.
// This method may fill out[0] and out[1] in one call.
function pointToDataOnlyHeaderFillOut(ctx, partialOut, dimIdx, dims) {
  var otherDimIdx = 1 - dimIdx;
  if (ctx[XY[dimIdx]] === CtxPointToDataAreaType.outside) {
    return;
  }
  for (dims[XY[dimIdx]].resetCellIterator(_ptdDimCellIt); _ptdDimCellIt.next();) {
    var cell = _ptdDimCellIt.item;
    if (isCoordInRect(ctx.point[dimIdx], cell.rect, dimIdx) && isCoordInRect(ctx.point[otherDimIdx], cell.rect, otherDimIdx)) {
      // non-leaves are also allowed to be located.
      // If the point is in x or y dimension cell area, should check both x and y coord to
      // determine a cell; in this way a non-leaf cell can be determined.
      partialOut[dimIdx] = cell.ordinal;
      partialOut[otherDimIdx] = cell.id[XY[otherDimIdx]];
      return;
    }
  }
}
// Assume partialOut has been set to NaN outside.
// This method may fill out[0] and out[1] in one call.
function pointToDataBodyCornerFillOut(ctx, partialOut, dimIdx, dims) {
  if (ctx[XY[dimIdx]] === CtxPointToDataAreaType.outside) {
    return;
  }
  var dim = ctx[XY[dimIdx]] === CtxPointToDataAreaType.inCorner ? dims[XY[1 - dimIdx]] : dims[XY[dimIdx]];
  for (dim.resetLayoutIterator(_ptdLevelIt, dimIdx); _ptdLevelIt.next();) {
    if (isCoordInLayoutInfo(ctx.point[dimIdx], _ptdLevelIt.item)) {
      partialOut[dimIdx] = _ptdLevelIt.item.id[XY[dimIdx]];
      return;
    }
  }
}
function isCoordInLayoutInfo(coord, cell) {
  return cell.xy <= coord && coord <= cell.xy + cell.wh;
}
function isCoordInRect(coord, rect, dimIdx) {
  return rect[XY[dimIdx]] <= coord && coord <= rect[XY[dimIdx]] + rect[WH[dimIdx]];
}
export default Matrix;