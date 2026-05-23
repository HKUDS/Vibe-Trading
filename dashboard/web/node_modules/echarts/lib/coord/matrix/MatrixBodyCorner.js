
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
import { createHashMap, each, extend, isArray, isObject } from 'zrender/lib/core/util.js';
import { error } from '../../util/log.js';
import Point from 'zrender/lib/core/Point.js';
import { resolveXYLocatorRangeByCellMerge, MatrixClampOption, parseCoordRangeOption, fillIdSpanFromLocatorRange, createNaNRectLike, isXYLocatorRangeInvalidOnDim, resetXYLocatorRange, cloneXYLocatorRange } from './matrixCoordHelper.js';
/**
 * Lifetime: the same with `MatrixModel`, but different from `coord/Matrix`.
 */
var MatrixBodyCorner = /** @class */function () {
  function MatrixBodyCorner(kind, bodyOrCornerModel, dims) {
    this._model = bodyOrCornerModel;
    this._dims = dims;
    this._kind = kind;
    this._cellMergeOwnerList = [];
  }
  /**
   * Can not be called before series models initialization finished, since the ordinalMeta may
   * use collect the values from `series.data` in series initialization.
   */
  MatrixBodyCorner.prototype._ensureCellMap = function () {
    var self = this;
    var _cellMap = self._cellMap;
    if (!_cellMap) {
      _cellMap = self._cellMap = createHashMap();
      fillCellMap();
    }
    return _cellMap;
    function fillCellMap() {
      var parsedList = [];
      var cellOptionList = self._model.getShallow('data');
      if (cellOptionList && !isArray(cellOptionList)) {
        if (process.env.NODE_ENV !== 'production') {
          error("matrix." + cellOptionList + ".data must be an array if specified.");
        }
        cellOptionList = null;
      }
      each(cellOptionList, function (option, idx) {
        if (!isObject(option) || !isArray(option.coord)) {
          if (process.env.NODE_ENV !== 'production') {
            error("Illegal matrix." + self._kind + ".data[" + idx + "], must be a {coord: [...], ...}");
          }
          return;
        }
        var locatorRange = resetXYLocatorRange([]);
        var reasonArr = null;
        if (process.env.NODE_ENV !== 'production') {
          reasonArr = [];
        }
        parseCoordRangeOption(locatorRange, reasonArr, option.coord, self._dims, option.coordClamp ? MatrixClampOption[self._kind] : MatrixClampOption.none);
        if (isXYLocatorRangeInvalidOnDim(locatorRange, 0) || isXYLocatorRangeInvalidOnDim(locatorRange, 1)) {
          if (process.env.NODE_ENV !== 'production') {
            error("Can not determine cells by option matrix." + self._kind + ".data[" + idx + "]: " + ("" + reasonArr.join(' ')));
          }
          return;
        }
        var cellMergeOwner = option && option.mergeCells;
        var parsed = {
          id: new Point(),
          span: new Point(),
          locatorRange: locatorRange,
          option: option,
          cellMergeOwner: cellMergeOwner
        };
        fillIdSpanFromLocatorRange(parsed, locatorRange);
        // The order of the `parsedList` determines the precedence of the styles, if there
        // are overlaps between ranges specified in different items. Preserve the original
        // order of `matrix.body/corner/data` to make it predictable for users.
        parsedList.push(parsed);
      });
      // Resolve cell merging intersection - union to a larger rect.
      var mergedMarkList = [];
      for (var parsedIdx = 0; parsedIdx < parsedList.length; parsedIdx++) {
        var parsed = parsedList[parsedIdx];
        if (!parsed.cellMergeOwner) {
          continue;
        }
        var locatorRange = parsed.locatorRange;
        resolveXYLocatorRangeByCellMerge(locatorRange, mergedMarkList, parsedList, parsedIdx);
        for (var idx = 0; idx < parsedIdx; idx++) {
          if (mergedMarkList[idx]) {
            parsedList[idx].cellMergeOwner = false;
          }
        }
        if (locatorRange[0][0] !== parsed.id.x || locatorRange[1][0] !== parsed.id.y) {
          // The top-left cell of the unioned locatorRange is not this cell any more.
          parsed.cellMergeOwner = false;
          // Reconcile: simply use the last style and value option if multiple styles involved
          // in a merged area, since there might be no commonly used merge strategy.
          var newOption = extend({}, parsed.option);
          newOption.coord = null;
          var newParsed = {
            id: new Point(),
            span: new Point(),
            locatorRange: locatorRange,
            option: newOption,
            cellMergeOwner: true
          };
          fillIdSpanFromLocatorRange(newParsed, locatorRange);
          parsedList.push(newParsed);
        }
      }
      // Assign options to cells.
      each(parsedList, function (parsed) {
        var topLeftCell = ensureBodyOrCornerCell(parsed.id.x, parsed.id.y);
        if (parsed.cellMergeOwner) {
          topLeftCell.cellMergeOwner = true;
          topLeftCell.span = parsed.span;
          topLeftCell.locatorRange = parsed.locatorRange;
          topLeftCell.spanRect = createNaNRectLike();
          self._cellMergeOwnerList.push(topLeftCell);
        }
        if (!parsed.cellMergeOwner && !parsed.option) {
          return;
        }
        for (var yidx = 0; yidx < parsed.span.y; yidx++) {
          for (var xidx = 0; xidx < parsed.span.x; xidx++) {
            var cell = ensureBodyOrCornerCell(parsed.id.x + xidx, parsed.id.y + yidx);
            // If multiple style options are defined on a cell, the later ones takes precedence.
            cell.option = parsed.option;
            if (parsed.cellMergeOwner) {
              cell.inSpanOf = topLeftCell;
            }
          }
        }
      });
    } // End of fillCellMap
    function ensureBodyOrCornerCell(x, y) {
      var key = makeCellMapKey(x, y);
      var cell = _cellMap.get(key);
      if (!cell) {
        cell = _cellMap.set(key, {
          id: new Point(x, y),
          option: null,
          inSpanOf: null,
          span: null,
          spanRect: null,
          locatorRange: null,
          cellMergeOwner: false
        });
      }
      return cell;
    }
  };
  /**
   * Body cells or corner cell are not commonly defined specifically, especially in a large
   * table, thus his is a sparse data structure - bodys or corner cells exist only if there
   * are options specified to it (in `matrix.body.data` or `matrix.corner.data`);
   * otherwise, return `NullUndefined`.
   */
  MatrixBodyCorner.prototype.getCell = function (xy) {
    // Assert xy do not contain NaN
    return this._ensureCellMap().get(makeCellMapKey(xy[0], xy[1]));
  };
  /**
   * Only cell existing (has specific definition or props) will be travelled.
   */
  MatrixBodyCorner.prototype.travelExistingCells = function (cb) {
    this._ensureCellMap().each(cb);
  };
  /**
   * @param locatorRange Must be the return of `parseCoordRangeOption`.
   */
  MatrixBodyCorner.prototype.expandRangeByCellMerge = function (locatorRange) {
    if (!isXYLocatorRangeInvalidOnDim(locatorRange, 0) && !isXYLocatorRangeInvalidOnDim(locatorRange, 1) && locatorRange[0][0] === locatorRange[0][1] && locatorRange[1][0] === locatorRange[1][1]) {
      // If it locates to a single cell, use this quick path to avoid travelling.
      // It is based on the fact that any cell is not contained by more than one cell merging rect.
      _tmpERBCMLocator[0] = locatorRange[0][0];
      _tmpERBCMLocator[1] = locatorRange[1][0];
      var cell = this.getCell(_tmpERBCMLocator);
      var inSpanOf = cell && cell.inSpanOf;
      if (inSpanOf) {
        cloneXYLocatorRange(locatorRange, inSpanOf.locatorRange);
        return;
      }
    }
    var list = this._cellMergeOwnerList;
    resolveXYLocatorRangeByCellMerge(locatorRange, null, list, list.length);
  };
  return MatrixBodyCorner;
}();
export { MatrixBodyCorner };
var _tmpERBCMLocator = [];
function makeCellMapKey(x, y) {
  return x + "|" + y;
}