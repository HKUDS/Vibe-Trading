
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
import createSeriesDataSimply from '../helper/createSeriesDataSimply.js';
import SeriesModel from '../../model/Series.js';
import geoSourceManager from '../../coord/geo/geoSourceManager.js';
import { makeSeriesEncodeForNameBased } from '../../data/helper/sourceHelper.js';
import { createTooltipMarkup } from '../../component/tooltip/tooltipMarkup.js';
import { createSymbol } from '../../util/symbol.js';
import { COORD_SYS_USAGE_KIND_BOX, decideCoordSysUsageKind } from '../../core/CoordinateSystem.js';
import tokens from '../../visual/tokens.js';
export var SERIES_TYPE_MAP = 'map';
var MapSeries = /** @class */function (_super) {
  __extends(MapSeries, _super);
  function MapSeries() {
    var _this = _super !== null && _super.apply(this, arguments) || this;
    _this.type = MapSeries.type;
    _this.getTooltipPosition = function (dataIndex) {
      if (dataIndex != null) {
        var name_1 = this.getData().getName(dataIndex);
        var geo = this.coordinateSystem;
        var region = geo.getRegion(name_1);
        return region && geo.dataToPoint(region.getCenter());
      }
    };
    return _this;
  }
  MapSeries.prototype.getInitialData = function (option) {
    var data = createSeriesDataSimply(this, {
      coordDimensions: ['value'],
      encodeDefaulter: zrUtil.curry(makeSeriesEncodeForNameBased, this)
    });
    var dataNameIndexMap = zrUtil.createHashMap();
    var toAppendItems = [];
    for (var i = 0, len = data.count(); i < len; i++) {
      var name_2 = data.getName(i);
      dataNameIndexMap.set(name_2, i);
    }
    var geoSource = geoSourceManager.load(this.getMapType(), this.option.nameMap, this.option.nameProperty);
    zrUtil.each(geoSource.regions, function (region) {
      var name = region.name;
      var dataNameIdx = dataNameIndexMap.get(name);
      // apply specified echarts style in GeoJSON data
      var specifiedGeoJSONRegionStyle = region.properties && region.properties.echartsStyle;
      var dataItem;
      if (dataNameIdx == null) {
        dataItem = {
          name: name
        };
        toAppendItems.push(dataItem);
      } else {
        dataItem = data.getRawDataItem(dataNameIdx);
      }
      specifiedGeoJSONRegionStyle && zrUtil.merge(dataItem, specifiedGeoJSONRegionStyle);
    });
    // Complete data with missing regions. The consequent processes (like visual
    // map and render) can not be performed without a "full data". For example,
    // find `dataIndex` by name.
    data.appendData(toAppendItems);
    return data;
  };
  /**
   * If no host geo model, return null, which means using a
   * inner exclusive geo model.
   */
  MapSeries.prototype.getHostGeoModel = function () {
    if (decideCoordSysUsageKind(this).kind === COORD_SYS_USAGE_KIND_BOX) {
      // Always use an internal geo if specify as `COORD_SYS_USAGE_KIND_BOX`.
      // Notice that currently we do not support laying out a geo based on
      // another geo, but preserve the possibility.
      return;
    }
    return this.getReferringComponents('geo', {
      useDefault: false,
      enableAll: false,
      enableNone: false
    }).models[0];
  };
  MapSeries.prototype.getMapType = function () {
    return (this.getHostGeoModel() || this).option.map;
  };
  // _fillOption(option, mapName) {
  // Shallow clone
  // option = zrUtil.extend({}, option);
  // option.data = geoCreator.getFilledRegions(option.data, mapName, option.nameMap);
  // return option;
  // }
  MapSeries.prototype.getRawValue = function (dataIndex) {
    // Use value stored in data instead because it is calculated from multiple series
    // FIXME Provide all value of multiple series ?
    var data = this.getData();
    return data.get(data.mapDimension('value'), dataIndex);
  };
  /**
   * Get model of region
   */
  MapSeries.prototype.getRegionModel = function (regionName) {
    var data = this.getData();
    return data.getItemModel(data.indexOfName(regionName));
  };
  /**
   * Map tooltip formatter
   */
  MapSeries.prototype.formatTooltip = function (dataIndex, multipleSeries, dataType) {
    // FIXME originalData and data is a bit confusing
    var data = this.getData();
    var value = this.getRawValue(dataIndex);
    var name = data.getName(dataIndex);
    var seriesNames = [];
    zrUtil.each(this.seriesGroup.f, function (mapSeries) {
      var otherIndex = mapSeries.originalData.indexOfName(name);
      var valueDim = data.mapDimension('value');
      if (!isNaN(mapSeries.originalData.get(valueDim, otherIndex))) {
        seriesNames.push(mapSeries.name);
      }
    });
    return createTooltipMarkup('section', {
      header: seriesNames.join(', '),
      noHeader: !seriesNames.length,
      blocks: [createTooltipMarkup('nameValue', {
        name: name,
        value: value
      })]
    });
  };
  MapSeries.prototype.getLegendIcon = function (opt) {
    var iconType = opt.icon || 'roundRect';
    var icon = createSymbol(iconType, 0, 0, opt.itemWidth, opt.itemHeight, opt.itemStyle.fill);
    icon.setStyle(opt.itemStyle);
    // Map do not use itemStyle.borderWidth as border width
    icon.style.stroke = 'none';
    // No rotation because no series visual symbol for map
    if (iconType.indexOf('empty') > -1) {
      icon.style.stroke = icon.style.fill;
      icon.style.fill = tokens.color.neutral00;
      icon.style.lineWidth = 2;
    }
    return icon;
  };
  MapSeries.prototype.__ownRoamView = function () {
    return mapSeriesNeedsDrawMap(this) ? this.coordinateSystem.view : null;
  };
  MapSeries.type = 'series.' + SERIES_TYPE_MAP;
  MapSeries.dependencies = ['geo'];
  MapSeries.layoutMode = 'box';
  MapSeries.defaultOption = {
    // 一级层叠
    // zlevel: 0,
    // 二级层叠
    z: 2,
    coordinateSystem: 'geo',
    // map should be explicitly specified since ec3.
    map: '',
    // If `geoIndex` is not specified, a exclusive geo will be
    // created. Otherwise use the specified geo component, and
    // `map` and `mapType` are ignored.
    // geoIndex: 0,
    // 'center' | 'left' | 'right' | 'x%' | {number}
    left: 'center',
    // 'center' | 'top' | 'bottom' | 'x%' | {number}
    top: 'center',
    // right
    // bottom
    // width:
    // height
    // Aspect is width / height. Inited to be geoJson bbox aspect
    // This parameter is used for scale this aspect
    // Default value:
    // for geoSVG source: 1,
    // for geoJSON source: 0.75.
    aspectScale: null,
    // Layout with center and size
    // If you want to put map in a fixed size box with right aspect ratio
    // This two properties may be more convenient.
    // layoutCenter: [50%, 50%]
    // layoutSize: 100
    showLegendSymbol: true,
    // Define left-top, right-bottom coords to control view
    // For example, [ [180, 90], [-180, -90] ],
    // higher priority than center and zoom
    boundingCoords: null,
    // Default on center of map
    center: null,
    zoom: 1,
    scaleLimit: null,
    selectedMode: true,
    label: {
      show: false,
      color: tokens.color.tertiary
    },
    // scaleLimit: null,
    itemStyle: {
      borderWidth: 0.5,
      borderColor: tokens.color.border,
      areaColor: tokens.color.background
    },
    emphasis: {
      label: {
        show: true,
        color: tokens.color.primary
      },
      itemStyle: {
        areaColor: tokens.color.highlight
      }
    },
    select: {
      label: {
        show: true,
        color: tokens.color.primary
      },
      itemStyle: {
        color: tokens.color.highlight
      }
    },
    nameProperty: 'name'
  };
  return MapSeries;
}(SeriesModel);
/**
 * Has exclusive geo, rahter than depends on a separate geo componet.
 */
export function mapSeriesGroupHasOwnGeo(groupKey) {
  return groupKey.indexOf('i') === 0;
}
export function mapSeriesNeedsDrawMap(mapSeries) {
  // Within a MAP_SERIES_GROUP, only `mainSeries` has `needsDrawMap: true`.
  return getMainMapSeries(mapSeries.seriesGroup) === mapSeries && !mapSeries.getHostGeoModel();
}
export function getMainMapSeries(mapSeriesGroup) {
  // The first series after filtering in a MAP_SERIES_GROUP.
  return mapSeriesGroup.f[0];
}
/**
 * @tutorial [MAP_SERIES_GROUP]
 *  - For map series that reference external geo components (typically via `geoIndex` or `geoId` in ec option),
 *    a map series group is all map series that reference to the same geo component.
 *  - For other map series,
 *    a map series group is all map series that use the same `map` in ec option.
 *  NOTICE: series filtering (typically by legend) matters:
 *   If this method is executed before series filtering, all series are included,
 *   otherwise, series filtered out are excluded.
 *   When legend disables the original first series, the original second series takes the responsibility
 *   to render map (via its `MapDraw`).
 */
export function buildAllMapSeriesGroups(ecModel, beforeSeriesFiltering) {
  var allMapSeriesGroups = {};
  ecModel.eachRawSeriesByType(SERIES_TYPE_MAP, function (seriesModel) {
    var hostGeoModel = seriesModel.getHostGeoModel();
    var key = hostGeoModel ? 'o' + hostGeoModel.id : 'i' + seriesModel.getMapType();
    var group = allMapSeriesGroups[key] = allMapSeriesGroups[key] || {
      f: [],
      r: []
    };
    if (!ecModel.isSeriesFiltered(seriesModel) && !beforeSeriesFiltering) {
      group.f.push(seriesModel);
    }
    group.r.push(seriesModel);
  });
  return allMapSeriesGroups;
}
export default MapSeries;