
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
import { createHashMap, defaults, each, eqNaN, isArray, isObject, isString } from 'zrender/lib/core/util.js';
import Point from 'zrender/lib/core/Point.js';
import OrdinalMeta from '../../data/OrdinalMeta.js';
import Ordinal from '../../scale/Ordinal.js';
import { WH, XY } from '../../util/graphic.js';
import { ListIterator } from '../../util/model.js';
import { createNaNRectLike, setDimXYValue, MatrixCellLayoutInfoType } from './matrixCoordHelper.js';
import { error } from '../../util/log.js';
import { mathMax } from '../../util/number.js';
/**
 * Lifetime: the same with `MatrixModel`, but different from `coord/Matrix`.
 */
var MatrixDim = /** @class */function () {
  function MatrixDim(dim, dimModel) {
    // Under the current definition, every leave corresponds a unit cell,
    // and leaves can serve as the locator of cells.
    // Therefore make sure:
    //  - The first `_leavesCount` elements in `_cells` are leaves.
    //  - `_cells[leaf.id[XY[this.dimIdx]]]` is the leaf itself.
    //  - Leaves of each subtree are placed together, that is, the leaves of a dimCell are:
    //    `this._cells.slice(dimCell.firstLeafLocator, dimCell.span[XY[this.dimIdx]])`
    this._cells = [];
    // Can be visited by `_levels[cell.level]` or `_levels[cell.id[1 - dimIdx] + _levels.length]`.
    // Items are never be null/undefined after initialized.
    this._levels = [];
    this.dim = dim;
    this.dimIdx = dim === 'x' ? 0 : 1;
    this._model = dimModel;
    this._uniqueValueGen = createUniqueValueGenerator(dim);
    var dimModelData = dimModel.get('data', true);
    var length = dimModel.get('length', true);
    if (dimModelData != null && !isArray(dimModelData)) {
      if (process.env.NODE_ENV !== 'production') {
        error("Illegal echarts option - matrix." + this.dim + ".data must be an array if specified.");
      }
      dimModelData = [];
    }
    if (dimModelData) {
      this._initByDimModelData(dimModelData);
    } else if (length != null) {
      dimModelData = Array(length);
      for (var i = 0; i < length; i++) {
        dimModelData[i] = null;
      }
      this._initByDimModelData(dimModelData);
    } else {
      this._initBySeriesData();
    }
  }
  MatrixDim.prototype._initByDimModelData = function (dimModelData) {
    var self = this;
    var _cells = self._cells;
    var _levels = self._levels;
    var sameLocatorCellsLists = []; // Save for sorting.
    var _cellCount = 0;
    self._leavesCount = traverseInitCells(dimModelData, 0, 0);
    postInitCells();
    return;
    function traverseInitCells(dimModelData, firstLeafLocator, level) {
      var totalSpan = 0;
      if (!dimModelData) {
        return totalSpan;
      }
      each(dimModelData, function (option, optionIdx) {
        var invalidOption = false;
        var cellOption;
        if (isString(option)) {
          cellOption = {
            value: option
          };
        } else if (isObject(option)) {
          cellOption = option;
          if (option.value != null && !isString(option.value)) {
            invalidOption = true;
            cellOption = {
              value: null
            };
          }
        } else {
          cellOption = {
            value: null
          };
          if (option != null) {
            invalidOption = true;
          }
        }
        if (invalidOption) {
          if (process.env.NODE_ENV !== 'production') {
            error("Illegal echarts option - matrix." + self.dim + ".data[" + optionIdx + "]" + ' must be `string | {value: string}`.');
          }
        }
        var cell = {
          type: MatrixCellLayoutInfoType.nonLeaf,
          ordinal: NaN,
          level: level,
          firstLeafLocator: firstLeafLocator,
          id: new Point(),
          span: setDimXYValue(new Point(), self.dimIdx, 1, 1),
          option: cellOption,
          xy: NaN,
          wh: NaN,
          dim: self,
          rect: createNaNRectLike()
        };
        _cellCount++;
        (sameLocatorCellsLists[firstLeafLocator] || (sameLocatorCellsLists[firstLeafLocator] = [])).push(cell);
        if (!_levels[level]) {
          // Create a level only if at least one cell exists.
          _levels[level] = {
            type: MatrixCellLayoutInfoType.level,
            xy: NaN,
            wh: NaN,
            option: null,
            id: new Point(),
            dim: self
          };
        }
        var childrenSpan = traverseInitCells(cellOption.children, firstLeafLocator, level + 1);
        var subSpan = Math.max(1, childrenSpan);
        cell.span[XY[self.dimIdx]] = subSpan;
        totalSpan += subSpan;
        firstLeafLocator += subSpan;
      });
      return totalSpan;
    }
    function postInitCells() {
      // Sort to make sure the leaves are at the beginning, so that
      // they can be used as the locator of body cells.
      var categories = [];
      while (_cells.length < _cellCount) {
        for (var locator = 0; locator < sameLocatorCellsLists.length; locator++) {
          var cell = sameLocatorCellsLists[locator].pop();
          if (cell) {
            cell.ordinal = categories.length;
            var val = cell.option.value;
            categories.push(val);
            _cells.push(cell);
            self._uniqueValueGen.calcDupBase(val);
          }
        }
      }
      self._uniqueValueGen.ensureValueUnique(categories, _cells);
      var ordinalMeta = self._ordinalMeta = new OrdinalMeta({
        categories: categories,
        needCollect: false,
        deduplication: false
      });
      self._scale = new Ordinal({
        ordinalMeta: ordinalMeta
      });
      for (var idx = 0; idx < self._leavesCount; idx++) {
        var leaf = self._cells[idx];
        leaf.type = MatrixCellLayoutInfoType.leaf;
        // Handle the tree level variation: enlarge the span of the leaves to reach the body cells.
        leaf.span[XY[1 - self.dimIdx]] = self._levels.length - leaf.level;
      }
      self._initCellsId();
      self._initLevelIdOptions();
    }
  };
  MatrixDim.prototype._initBySeriesData = function () {
    var self = this;
    self._leavesCount = 0;
    self._levels = [{
      type: MatrixCellLayoutInfoType.level,
      xy: NaN,
      wh: NaN,
      option: null,
      id: new Point(),
      dim: self
    }];
    self._initLevelIdOptions();
    var ordinalMeta = self._ordinalMeta = new OrdinalMeta({
      needCollect: true,
      deduplication: true,
      onCollect: function (value, ordinalNumber) {
        var cell = self._cells[ordinalNumber] = {
          type: MatrixCellLayoutInfoType.leaf,
          ordinal: ordinalNumber,
          level: 0,
          firstLeafLocator: ordinalNumber,
          id: new Point(),
          span: setDimXYValue(new Point(), self.dimIdx, 1, 1),
          // Theoretically `value` is from `dataset` or `series.data`, so it may be any type.
          // Do not restrict this case for user's convenience, and here simply convert it to
          // string for display.
          option: {
            value: value + ''
          },
          xy: NaN,
          wh: NaN,
          dim: self,
          rect: createNaNRectLike()
        };
        self._leavesCount++;
        self._setCellId(cell);
      }
    });
    self._scale = new Ordinal({
      ordinalMeta: ordinalMeta
    });
  };
  MatrixDim.prototype._setCellId = function (cell) {
    var levelsLen = this._levels.length;
    var dimIdx = this.dimIdx;
    setDimXYValue(cell.id, dimIdx, cell.firstLeafLocator, cell.level - levelsLen);
  };
  MatrixDim.prototype._initCellsId = function () {
    var levelsLen = this._levels.length;
    var dimIdx = this.dimIdx;
    each(this._cells, function (cell) {
      setDimXYValue(cell.id, dimIdx, cell.firstLeafLocator, cell.level - levelsLen);
    });
  };
  MatrixDim.prototype._initLevelIdOptions = function () {
    var levelsLen = this._levels.length;
    var dimIdx = this.dimIdx;
    var levelOptionList = this._model.get('levels', true);
    levelOptionList = isArray(levelOptionList) ? levelOptionList : [];
    each(this._levels, function (levelCfg, level) {
      setDimXYValue(levelCfg.id, dimIdx, 0, level - levelsLen);
      levelCfg.option = levelOptionList[level];
    });
  };
  MatrixDim.prototype.shouldShow = function () {
    return !!this._model.getShallow('show', true);
  };
  /**
   * Iterate leaves (they are layout units) if dimIdx === this.dimIdx.
   * Iterate levels if dimIdx !== this.dimIdx.
   */
  MatrixDim.prototype.resetLayoutIterator = function (it, dimIdx, startLocator, count) {
    it = it || new ListIterator();
    if (dimIdx === this.dimIdx) {
      var len = this._leavesCount;
      var startIdx = startLocator != null ? Math.max(0, startLocator) : 0;
      count = count != null ? Math.min(count, len) : len;
      it.reset(this._cells, startIdx, startIdx + count);
    } else {
      var len = this._levels.length;
      // Corner locator is from `-this._levels.length` to `-1`.
      var startIdx = startLocator != null ? Math.max(0, startLocator + len) : 0;
      count = count != null ? Math.min(count, len) : len;
      it.reset(this._levels, startIdx, startIdx + count);
    }
    return it;
  };
  MatrixDim.prototype.resetCellIterator = function (it) {
    return (it || new ListIterator()).reset(this._cells, 0);
  };
  MatrixDim.prototype.resetLevelIterator = function (it) {
    return (it || new ListIterator()).reset(this._levels, 0);
  };
  MatrixDim.prototype.getLayout = function (outRect, dimIdx, locator) {
    var layout = this.getUnitLayoutInfo(dimIdx, locator);
    outRect[XY[dimIdx]] = layout ? layout.xy : NaN;
    outRect[WH[dimIdx]] = layout ? layout.wh : NaN;
  };
  /**
   * Get leaf cell or get level info.
   * Should be able to return null/undefined if not found on x or y, thus input `dimIdx` is needed.
   */
  MatrixDim.prototype.getUnitLayoutInfo = function (dimIdx, locator) {
    return dimIdx === this.dimIdx ? locator < this._leavesCount ? this._cells[locator] : undefined : this._levels[locator + this._levels.length];
  };
  /**
   * Get dimension cell by data, including leaves and non-leaves.
   */
  MatrixDim.prototype.getCell = function (value) {
    var ordinal = this._scale.parse(value);
    return eqNaN(ordinal) ? undefined : this._cells[ordinal];
  };
  /**
   * Get leaf count or get level count.
   */
  MatrixDim.prototype.getLocatorCount = function (dimIdx) {
    return dimIdx === this.dimIdx ? this._leavesCount : this._levels.length;
  };
  MatrixDim.prototype.getOrdinalMeta = function () {
    return this._ordinalMeta;
  };
  return MatrixDim;
}();
export { MatrixDim };
function createUniqueValueGenerator(dim) {
  var dimUpper = dim.toUpperCase();
  var defaultValReg = new RegExp("^" + dimUpper + "([0-9]+)$");
  var dupBase = 0;
  function calcDupBase(val) {
    var matchResult;
    if (val != null && (matchResult = val.match(defaultValReg))) {
      dupBase = mathMax(dupBase, +matchResult[1] + 1);
    }
  }
  function makeUniqueValue() {
    return "" + dimUpper + dupBase++;
  }
  // Duplicated value is allowed, because the `matrix.x/y.data` can be a tree and it's reasonable
  // that leaves in different subtrees has the same text. But only the first one is allowed to be
  // queried by the text, and the other ones can only be queried by index.
  // Additionally, `matrix.x/y.data: [null, null, ...]` is allowed.
  function ensureValueUnique(categories, cells) {
    // A simple way to deduplicate or handle illegal or not specified values to avoid unexpected behaviors.
    // The tree structure should not be broken even if duplicated.
    var cateMap = createHashMap();
    for (var idx = 0; idx < categories.length; idx++) {
      var value = categories[idx];
      // value may be set to NullUndefined by users or if illegal.
      if (value == null || cateMap.get(value) != null) {
        // Still display the original option.value if duplicated, but loose the ability to query by text.
        categories[idx] = value = makeUniqueValue();
        cells[idx].option = defaults({
          value: value
        }, cells[idx].option);
      }
      cateMap.set(value, true);
    }
  }
  return {
    calcDupBase: calcDupBase,
    ensureValueUnique: ensureValueUnique
  };
}