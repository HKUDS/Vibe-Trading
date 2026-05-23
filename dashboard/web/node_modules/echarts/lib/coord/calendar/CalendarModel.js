
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
import { __extends } from "tslib";
import * as zrUtil from 'zrender/lib/core/util.js';
import ComponentModel from '../../model/Component.js';
import { getLayoutParams, sizeCalculable, mergeLayoutParam } from '../../util/layout.js';
import tokens from '../../visual/tokens.js';
var CalendarModel = /** @class */function (_super) {
  __extends(CalendarModel, _super);
  function CalendarModel() {
    var _this = _super !== null && _super.apply(this, arguments) || this;
    _this.type = CalendarModel.type;
    return _this;
  }
  /**
   * @override
   */
  CalendarModel.prototype.init = function (option, parentModel, ecModel) {
    var inputPositionParams = getLayoutParams(option);
    _super.prototype.init.apply(this, arguments);
    mergeAndNormalizeLayoutParams(option, inputPositionParams);
  };
  /**
   * @override
   */
  CalendarModel.prototype.mergeOption = function (option) {
    _super.prototype.mergeOption.apply(this, arguments);
    mergeAndNormalizeLayoutParams(this.option, option);
  };
  CalendarModel.prototype.getCellSize = function () {
    // Has been normalized
    return this.option.cellSize;
  };
  CalendarModel.type = 'calendar';
  CalendarModel.layoutMode = 'box';
  CalendarModel.defaultOption = {
    // zlevel: 0,
    // TODO: theoretically, the z of the calendar should be lower
    // than series, but we don't want the series to be displayed
    // on top of the borders like month split line. To align with
    // the effect of previous versions, we set the z to 2 for now
    // until better solution is found.
    z: 2,
    left: 80,
    top: 60,
    cellSize: 20,
    // horizontal vertical
    orient: 'horizontal',
    // month separate line style
    splitLine: {
      show: true,
      lineStyle: {
        color: tokens.color.axisLine,
        width: 1,
        type: 'solid'
      }
    },
    // rect style  temporarily unused emphasis
    itemStyle: {
      color: tokens.color.neutral00,
      borderWidth: 1,
      borderColor: tokens.color.neutral10
    },
    // week text style
    dayLabel: {
      show: true,
      firstDay: 0,
      // start end
      position: 'start',
      margin: tokens.size.s,
      color: tokens.color.secondary
    },
    // month text style
    monthLabel: {
      show: true,
      // start end
      position: 'start',
      margin: tokens.size.s,
      // center or left
      align: 'center',
      formatter: null,
      color: tokens.color.secondary
    },
    // year text style
    yearLabel: {
      show: true,
      // top bottom left right
      position: null,
      margin: tokens.size.xl,
      formatter: null,
      color: tokens.color.quaternary,
      fontFamily: 'sans-serif',
      fontWeight: 'bolder',
      fontSize: 20
    }
  };
  return CalendarModel;
}(ComponentModel);
function mergeAndNormalizeLayoutParams(target, raw) {
  // Normalize cellSize
  var cellSize = target.cellSize;
  var cellSizeArr;
  if (!zrUtil.isArray(cellSize)) {
    cellSizeArr = target.cellSize = [cellSize, cellSize];
  } else {
    cellSizeArr = cellSize;
  }
  if (cellSizeArr.length === 1) {
    cellSizeArr[1] = cellSizeArr[0];
  }
  var ignoreSize = zrUtil.map([0, 1], function (hvIdx) {
    // If user have set `width` or both `left` and `right`, cellSizeArr
    // will be automatically set to 'auto', otherwise the default
    // setting of cellSizeArr will make `width` setting not work.
    if (sizeCalculable(raw, hvIdx)) {
      cellSizeArr[hvIdx] = 'auto';
    }
    return cellSizeArr[hvIdx] != null && cellSizeArr[hvIdx] !== 'auto';
  });
  mergeLayoutParam(target, raw, {
    type: 'box',
    ignoreSize: ignoreSize
  });
}
export default CalendarModel;