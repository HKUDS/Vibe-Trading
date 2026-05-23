
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
import ComponentModel from '../../model/Component.js';
import { getLayoutParams, mergeLayoutParam } from '../../util/layout.js';
import tokens from '../../visual/tokens.js';
// For backward compatibility, do not use a margin. Although the labels might touch the edge of
// the canvas, the chart canvas probably does not have an border or a different background color within a page.
export var OUTER_BOUNDS_DEFAULT = {
  left: 0,
  right: 0,
  top: 0,
  bottom: 0
};
export var OUTER_BOUNDS_CLAMP_DEFAULT = ['25%', '25%'];
export var COORD_SYS_TYPE_CARTESIAN_2D = 'cartesian2d';
var GridModel = /** @class */function (_super) {
  __extends(GridModel, _super);
  function GridModel() {
    return _super !== null && _super.apply(this, arguments) || this;
  }
  GridModel.prototype.mergeDefaultAndTheme = function (option, ecModel) {
    var outerBoundsCp = getLayoutParams(option.outerBounds);
    _super.prototype.mergeDefaultAndTheme.apply(this, arguments);
    if (outerBoundsCp && option.outerBounds) {
      mergeLayoutParam(option.outerBounds, outerBoundsCp);
    }
  };
  GridModel.prototype.mergeOption = function (newOption, ecModel) {
    _super.prototype.mergeOption.apply(this, arguments);
    if (this.option.outerBounds && newOption.outerBounds) {
      mergeLayoutParam(this.option.outerBounds, newOption.outerBounds);
    }
  };
  GridModel.type = 'grid';
  GridModel.dependencies = ['xAxis', 'yAxis'];
  GridModel.layoutMode = 'box';
  GridModel.defaultOption = {
    show: false,
    // zlevel: 0,
    z: 0,
    left: '15%',
    top: 65,
    right: '10%',
    bottom: 80,
    // If grid size contain label
    containLabel: false,
    outerBoundsMode: 'auto',
    outerBounds: OUTER_BOUNDS_DEFAULT,
    outerBoundsContain: 'all',
    outerBoundsClampWidth: OUTER_BOUNDS_CLAMP_DEFAULT[0],
    outerBoundsClampHeight: OUTER_BOUNDS_CLAMP_DEFAULT[1],
    // width: {totalWidth} - left - right,
    // height: {totalHeight} - top - bottom,
    backgroundColor: tokens.color.transparent,
    borderWidth: 1,
    borderColor: tokens.color.neutral30
  };
  return GridModel;
}(ComponentModel);
export default GridModel;