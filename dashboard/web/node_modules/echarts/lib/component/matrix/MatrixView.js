
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
import ComponentView from '../../view/Component.js';
import Model from '../../model/Model.js';
import BoundingRect from 'zrender/lib/core/BoundingRect.js';
import * as vectorUtil from 'zrender/lib/core/vector.js';
import { subPixelOptimize } from 'zrender/lib/graphic/helper/subPixelOptimize.js';
import { Rect, Line, XY, setTooltipConfig, expandOrShrinkRect } from '../../util/graphic.js';
import { clearTmpModel, ListIterator } from '../../util/model.js';
import { getECData } from '../../util/innerStore.js';
import { clone, retrieve2, isFunction, isString } from 'zrender/lib/core/util.js';
import { formatTplSimple } from '../../util/format.js';
import { invert } from 'zrender/lib/core/matrix.js';
import { setLabelStyle } from '../../label/labelStyle.js';
var round = Math.round;
var Z2_BACKGROUND = 0;
var Z2_OUTER_BORDER = 99;
var Z2_BODY_CORNER_CELL_DEFAULT = {
  normal: 25,
  special: 100
};
var Z2_DIMENSION_CELL_DEFAULT = {
  normal: 50,
  special: 125
};
var MatrixView = /** @class */function (_super) {
  __extends(MatrixView, _super);
  function MatrixView() {
    var _this = _super !== null && _super.apply(this, arguments) || this;
    _this.type = MatrixView.type;
    return _this;
  }
  MatrixView.prototype.render = function (matrixModel, ecModel) {
    this.group.removeAll();
    var group = this.group;
    var coordSys = matrixModel.coordinateSystem;
    var rect = coordSys.getRect();
    var xDimModel = matrixModel.getDimensionModel('x');
    var yDimModel = matrixModel.getDimensionModel('y');
    var xDim = xDimModel.dim;
    var yDim = yDimModel.dim;
    // PENDING:
    //  reuse the existing text and rect elements for performance?
    renderDimensionCells(group, matrixModel, ecModel);
    createBodyAndCorner(group, matrixModel, xDim, yDim, ecModel);
    var borderZ2Option = matrixModel.getShallow('borderZ2', true);
    var outerBorderZ2 = retrieve2(borderZ2Option, Z2_OUTER_BORDER);
    var dividerLineZ2 = outerBorderZ2 - 1;
    // Outer border and overall background. Use separate elements because of z-order:
    // The overall background should appear below any other elements.
    // But in most cases, the outer border and the divider line should be above the normal cell borders -
    // especially when cell borders have different colors. But users may highlight some specific cells by
    // overstirking their border, in which case it should be above the outer border.
    var bgStyle = matrixModel.getModel('backgroundStyle').getItemStyle(['borderWidth']);
    bgStyle.lineWidth = 0;
    var borderStyle = matrixModel.getModel('backgroundStyle').getItemStyle(['color', 'decal', 'shadowColor', 'shadowBlur', 'shadowOffsetX', 'shadowOffsetY']);
    borderStyle.fill = 'none';
    var bgRect = createMatrixRect(rect.clone(), bgStyle, Z2_BACKGROUND);
    var borderRect = createMatrixRect(rect.clone(), borderStyle, outerBorderZ2);
    bgRect.silent = true;
    borderRect.silent = true;
    group.add(bgRect);
    group.add(borderRect);
    // Header split line.
    var xDimCell0 = xDim.getUnitLayoutInfo(0, 0);
    var yDimCell0 = yDim.getUnitLayoutInfo(1, 0);
    if (xDimCell0 && yDimCell0) {
      if (xDim.shouldShow()) {
        group.add(createMatrixLine({
          x1: rect.x,
          y1: yDimCell0.xy,
          x2: rect.x + rect.width,
          y2: yDimCell0.xy
        }, xDimModel.getModel('dividerLineStyle').getLineStyle(), dividerLineZ2));
      }
      if (yDim.shouldShow()) {
        group.add(createMatrixLine({
          x1: xDimCell0.xy,
          y1: rect.y,
          x2: xDimCell0.xy,
          y2: rect.y + rect.height
        }, yDimModel.getModel('dividerLineStyle').getLineStyle(), dividerLineZ2));
      }
    }
  };
  MatrixView.type = 'matrix';
  return MatrixView;
}(ComponentView);
function renderDimensionCells(group, matrixModel, ecModel) {
  renderOnDimension(0);
  renderOnDimension(1);
  function renderOnDimension(dimIdx) {
    var thisDimModel = matrixModel.getDimensionModel(XY[dimIdx]);
    var thisDim = thisDimModel.dim;
    if (!thisDim.shouldShow()) {
      return;
    }
    var thisDimBgStyleModel = thisDimModel.getModel('itemStyle');
    var thisDimLabelModel = thisDimModel.getModel('label');
    var tooltipOption = matrixModel.getShallow('tooltip', true);
    var xyLocator = [];
    for (var it_1 = thisDim.resetCellIterator(); it_1.next();) {
      var dimCell = it_1.item;
      var shape = {};
      BoundingRect.copy(shape, dimCell.rect);
      vectorUtil.set(xyLocator, dimCell.id.x, dimCell.id.y);
      createMatrixCell(xyLocator, matrixModel, group, ecModel, dimCell.option, thisDimBgStyleModel, thisDimLabelModel, thisDimModel, shape, dimCell.option.value, Z2_DIMENSION_CELL_DEFAULT, tooltipOption, dimIdx === 0 ? 'x' : 'y');
    }
  }
}
function createBodyAndCorner(group, matrixModel, xDim, yDim, ecModel) {
  createBodyOrCornerCells('body', matrixModel.getBody(), xDim, yDim);
  if (xDim.shouldShow() && yDim.shouldShow()) {
    createBodyOrCornerCells('corner', matrixModel.getCorner(), yDim, xDim);
  }
  function createBodyOrCornerCells(bodyCornerOptionRoot, bodyOrCorner, dimForCoordX,
  // Can be `matrix.y` (transposed) for corners.
  dimForCoordY) {
    // Prevent inheriting from ancestor.
    var parentCellModel = new Model(matrixModel.getShallow(bodyCornerOptionRoot, true));
    var parentItemStyleModel = parentCellModel.getModel('itemStyle');
    var parentLabelModel = parentCellModel.getModel('label');
    var itx = new ListIterator();
    var ity = new ListIterator();
    var xyLocator = [];
    var tooltipOption = matrixModel.getShallow('tooltip', true);
    for (dimForCoordY.resetLayoutIterator(ity, 1); ity.next();) {
      for (dimForCoordX.resetLayoutIterator(itx, 0); itx.next();) {
        var xLayout = itx.item;
        var yLayout = ity.item;
        vectorUtil.set(xyLocator, xLayout.id.x, yLayout.id.y);
        var bodyCornerCell = bodyOrCorner.getCell(xyLocator);
        // If in span of an other body or corner cell, never render it.
        if (bodyCornerCell && bodyCornerCell.inSpanOf && bodyCornerCell.inSpanOf !== bodyCornerCell) {
          continue;
        }
        var shape = {};
        if (bodyCornerCell && bodyCornerCell.span) {
          BoundingRect.copy(shape, bodyCornerCell.spanRect);
        } else {
          xLayout.dim.getLayout(shape, 0, xyLocator[0]);
          yLayout.dim.getLayout(shape, 1, xyLocator[1]);
        }
        var bodyCornerCellOption = bodyCornerCell ? bodyCornerCell.option : null;
        createMatrixCell(xyLocator, matrixModel, group, ecModel, bodyCornerCellOption, parentItemStyleModel, parentLabelModel, parentCellModel, shape, bodyCornerCellOption ? bodyCornerCellOption.value : null, Z2_BODY_CORNER_CELL_DEFAULT, tooltipOption, bodyCornerOptionRoot);
      }
    }
  } // End of createBodyOrCornerCells
}
function createMatrixCell(xyLocator, matrixModel, group, ecModel, cellOption, parentItemStyleModel, parentLabelModel, parentCellModel, shape, textValue, zrCellDefault, tooltipOption, targetType) {
  var _a;
  // Do not use getModel - a quick performance optimization.
  _tmpCellItemStyleModel.option = cellOption ? cellOption.itemStyle : null;
  _tmpCellItemStyleModel.parentModel = parentItemStyleModel;
  _tmpCellModel.option = cellOption;
  _tmpCellModel.parentModel = parentCellModel;
  // Use different z2 because special border may be defined in itemStyle.
  var z2 = retrieve2(_tmpCellModel.getShallow('z2'), cellOption && cellOption.itemStyle ? zrCellDefault.special : zrCellDefault.normal);
  var tooltipOptionShow = tooltipOption && tooltipOption.show;
  var cellRect = createMatrixRect(shape, _tmpCellItemStyleModel.getItemStyle(), z2);
  group.add(cellRect);
  var cursorOption = _tmpCellModel.get('cursor');
  if (cursorOption != null) {
    cellRect.attr('cursor', cursorOption);
  }
  var cellText;
  if (textValue != null) {
    var text = textValue + '';
    _tmpCellLabelModel.option = cellOption ? cellOption.label : null;
    _tmpCellLabelModel.parentModel = parentLabelModel;
    // This is to accept `option.textStyle` as the default.
    _tmpCellLabelModel.ecModel = ecModel;
    var formatter = _tmpCellLabelModel.getShallow('formatter');
    if (formatter) {
      var params = {
        componentType: 'matrix',
        componentIndex: matrixModel.componentIndex,
        name: text,
        value: textValue,
        coord: xyLocator.slice(),
        $vars: ['name', 'value', 'coord']
      };
      if (isString(formatter)) {
        text = formatTplSimple(formatter, params);
      } else if (isFunction(formatter)) {
        var formattedText = formatter(params);
        if (formattedText != null) {
          text = formattedText + '';
        }
      }
    }
    setLabelStyle(cellRect,
    // Currently do not support other states (`emphasis`, `select`, `blur`)
    {
      normal: _tmpCellLabelModel
    }, {
      defaultText: text,
      autoOverflowArea: true,
      // By default based on boundingRect. But boundingRect contains borderWidth,
      // and borderWidth is half outside the cell. Thus specific `layoutRect` explicitly.
      layoutRect: clone(cellRect.shape)
    });
    cellText = cellRect.getTextContent();
    if (cellText) {
      cellText.z2 = z2 + 1;
      var style = cellText.style;
      if (style && style.overflow && style.overflow !== 'none' && style.lineOverflow) {
        // `overflow: 'break'/'breakAll'/'truncate'` does not guarantee prevention of overflow
        // when space is insufficient. Use a `clipPath` in such case.
        var clipShape = {};
        BoundingRect.copy(clipShape, shape);
        // `lineWidth` is half outside half inside the bounding rect.
        expandOrShrinkRect(clipShape, (((_a = cellRect.style) === null || _a === void 0 ? void 0 : _a.lineWidth) || 0) / 2, true, true);
        cellRect.updateInnerText();
        cellText.getLocalTransform(_tmpInnerTextTrans);
        invert(_tmpInnerTextTrans, _tmpInnerTextTrans);
        BoundingRect.applyTransform(clipShape, clipShape, _tmpInnerTextTrans);
        cellText.setClipPath(new Rect({
          shape: clipShape
        }));
      }
    }
    setTooltipConfig({
      el: cellRect,
      componentModel: matrixModel,
      itemName: text,
      itemTooltipOption: tooltipOption,
      formatterParamsExtra: {
        xyLocator: xyLocator.slice()
      }
    });
  }
  // Set silent
  var triggerEvent = matrixModel.get('triggerEvent', true);
  if (cellText) {
    var labelSilent = _tmpCellLabelModel.get('silent');
    // By default, silent: false is needed for triggerEvent or tooltip interaction.
    if (labelSilent == null) {
      labelSilent = !(triggerEvent || tooltipOptionShow);
    }
    cellText.silent = labelSilent;
    cellText.ignoreHostSilent = true;
  }
  var rectSilent = _tmpCellModel.get('silent');
  if (rectSilent == null) {
    rectSilent =
    // If no background color in cell, set `rect.silent: false` will cause that only
    // the border response to mouse hovering, which is probably weird.
    // So we deliberately make rect non-interactive if `silent` is not explicitly specified,
    // even if `triggerEvent` is set as `true`.
    !cellRect.style || cellRect.style.fill === 'none' || !cellRect.style.fill;
  }
  cellRect.silent = rectSilent;
  // Both `cellRect` (typically non-transparent) and `cellText` may trigger events, depending on both
  // `matrix.triggerEvent`, `matrix.xxx.silent` and `matrix.xxx.label.silent` settings.
  if (triggerEvent && cellRect) {
    var eventData = {
      componentType: 'matrix',
      componentIndex: matrixModel.componentIndex,
      matrixIndex: matrixModel.componentIndex,
      targetType: targetType,
      name: cellText && cellText.style ? cellText.style.text : undefined,
      value: textValue,
      coord: xyLocator.slice()
    };
    getECData(cellRect).eventData = eventData;
  }
  clearTmpModel(_tmpCellModel);
  clearTmpModel(_tmpCellItemStyleModel);
  clearTmpModel(_tmpCellLabelModel);
}
var _tmpCellModel = new Model();
var _tmpCellItemStyleModel = new Model();
var _tmpCellLabelModel = new Model();
var _tmpInnerTextTrans = [];
// FIXME: move all of the subpixel process to Matrix.ts resize, otherwise the result of
// `dataToLayout` is not consistent with this rendering, and the caller (like heatmap) can
// not precisely align with the matrix border.
function createMatrixRect(shape, style, z2) {
  // Currently `subPixelOptimizeRect` can not be used here because it will break rect alignment.
  // Optimize line and rect with the same direction.
  var lineWidth = style.lineWidth;
  if (lineWidth) {
    var x2Original = shape.x + shape.width;
    var y2Original = shape.y + shape.height;
    shape.x = subPixelOptimize(shape.x, lineWidth, true);
    shape.y = subPixelOptimize(shape.y, lineWidth, true);
    shape.width = subPixelOptimize(x2Original, lineWidth, true) - shape.x;
    shape.height = subPixelOptimize(y2Original, lineWidth, true) - shape.y;
  }
  return new Rect({
    shape: shape,
    style: style,
    z2: z2
  });
}
function createMatrixLine(shape, style, z2) {
  var lineWidth = style.lineWidth;
  if (lineWidth) {
    if (round(shape.x1 * 2) === round(shape.x2 * 2)) {
      shape.x1 = shape.x2 = subPixelOptimize(shape.x1, lineWidth, true);
    }
    if (round(shape.y1 * 2) === round(shape.y2 * 2)) {
      shape.y1 = shape.y2 = subPixelOptimize(shape.y1, lineWidth, true);
    }
  }
  return new Line({
    shape: shape,
    style: style,
    silent: true,
    z2: z2
  });
}
export default MatrixView;