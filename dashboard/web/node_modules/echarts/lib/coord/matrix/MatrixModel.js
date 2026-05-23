
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
import Model from '../../model/Model.js';
import { MatrixDim } from './MatrixDim.js';
import { MatrixBodyCorner } from './MatrixBodyCorner.js';
import tokens from '../../visual/tokens.js';
var defaultLabelOption = {
  show: true,
  color: tokens.color.secondary,
  // overflow: 'truncate',
  overflow: 'break',
  lineOverflow: 'truncate',
  padding: [2, 3, 2, 3],
  // Prefer to use `padding`, rather than distance.
  distance: 0
};
function makeDefaultCellItemStyleOption(isCorner) {
  return {
    color: 'none',
    borderWidth: 1,
    borderColor: isCorner ? 'none' : tokens.color.borderTint
  };
}
;
var defaultDimOption = {
  show: true,
  label: defaultLabelOption,
  itemStyle: makeDefaultCellItemStyleOption(false),
  silent: undefined,
  dividerLineStyle: {
    width: 1,
    color: tokens.color.border
  }
};
var defaultBodyOption = {
  label: defaultLabelOption,
  itemStyle: makeDefaultCellItemStyleOption(false),
  silent: undefined
};
var defaultCornerOption = {
  label: defaultLabelOption,
  itemStyle: makeDefaultCellItemStyleOption(true),
  silent: undefined
};
var defaultMatrixOption = {
  // As a most basic coord sys, `z` should be lower than
  // other series and coord sys, such as, grid.
  z: -50,
  left: '10%',
  top: '10%',
  right: '10%',
  bottom: '10%',
  x: defaultDimOption,
  y: defaultDimOption,
  body: defaultBodyOption,
  corner: defaultCornerOption,
  backgroundStyle: {
    color: 'none',
    borderColor: tokens.color.axisLine,
    borderWidth: 1
  },
  triggerEvent: false
};
var MatrixModel = /** @class */function (_super) {
  __extends(MatrixModel, _super);
  function MatrixModel() {
    var _this = _super !== null && _super.apply(this, arguments) || this;
    _this.type = MatrixModel.type;
    return _this;
  }
  MatrixModel.prototype.optionUpdated = function () {
    // Simply re-create all to follow model changes.
    var dimModels = this._dimModels = {
      // Do not use matrixModel as the parent model, for preventing from cascade-fetching options to it.
      x: new MatrixDimensionModel(this.get('x', true) || {}),
      y: new MatrixDimensionModel(this.get('y', true) || {})
    };
    dimModels.x.option.type = dimModels.y.option.type = 'category';
    var xDim = dimModels.x.dim = new MatrixDim('x', dimModels.x);
    var yDim = dimModels.y.dim = new MatrixDim('y', dimModels.y);
    var dims = {
      x: xDim,
      y: yDim
    };
    this._body = new MatrixBodyCorner('body', new Model(this.getShallow('body')), dims);
    this._corner = new MatrixBodyCorner('corner', new Model(this.getShallow('corner')), dims);
  };
  MatrixModel.prototype.getDimensionModel = function (dim) {
    return this._dimModels[dim];
  };
  MatrixModel.prototype.getBody = function () {
    return this._body;
  };
  MatrixModel.prototype.getCorner = function () {
    return this._corner;
  };
  MatrixModel.type = 'matrix';
  MatrixModel.layoutMode = 'box';
  MatrixModel.defaultOption = defaultMatrixOption;
  return MatrixModel;
}(ComponentModel);
var MatrixDimensionModel = /** @class */function (_super) {
  __extends(MatrixDimensionModel, _super);
  function MatrixDimensionModel() {
    return _super !== null && _super.apply(this, arguments) || this;
  }
  MatrixDimensionModel.prototype.getOrdinalMeta = function () {
    return this.dim.getOrdinalMeta();
  };
  return MatrixDimensionModel;
}(Model);
export { MatrixDimensionModel };
export default MatrixModel;