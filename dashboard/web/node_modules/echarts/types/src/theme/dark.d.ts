declare const theme: {
    darkMode: boolean;
    color: string[];
    backgroundColor: string;
    axisPointer: {
        lineStyle: {
            color: string;
        };
        crossStyle: {
            color: string;
        };
        label: {
            color: string;
        };
    };
    legend: {
        textStyle: {
            color: string;
        };
        pageTextStyle: {
            color: string;
        };
    };
    textStyle: {
        color: string;
    };
    title: {
        textStyle: {
            color: string;
        };
        subtextStyle: {
            color: string;
        };
    };
    toolbox: {
        iconStyle: {
            borderColor: string;
        };
        feature: {
            dataView: {
                backgroundColor: string;
                textColor: string;
                textareaColor: string;
                textareaBorderColor: string;
                buttonColor: string;
                buttonTextColor: string;
            };
        };
    };
    tooltip: {
        backgroundColor: string;
        defaultBorderColor: string;
        textStyle: {
            color: string;
        };
    };
    dataZoom: {
        borderColor: string;
        textStyle: {
            color: string;
        };
        brushStyle: {
            color: string;
        };
        handleStyle: {
            color: string;
            borderColor: string;
        };
        moveHandleStyle: {
            color: string;
        };
        emphasis: {
            handleStyle: {
                borderColor: string;
            };
        };
        dataBackground: {
            lineStyle: {
                color: string;
            };
            areaStyle: {
                color: string;
            };
        };
        selectedDataBackground: {
            lineStyle: {
                color: string;
            };
            areaStyle: {
                color: string;
            };
        };
    };
    visualMap: {
        textStyle: {
            color: string;
        };
        handleStyle: {
            borderColor: string;
        };
    };
    timeline: {
        lineStyle: {
            color: string;
        };
        label: {
            color: string;
        };
        controlStyle: {
            color: string;
            borderColor: string;
        };
    };
    calendar: {
        itemStyle: {
            color: string;
            borderColor: string;
        };
        dayLabel: {
            color: string;
        };
        monthLabel: {
            color: string;
        };
        yearLabel: {
            color: string;
        };
    };
    matrix: {
        x: {
            label: {
                color: string;
            };
            itemStyle: {
                borderColor: string;
            };
            dividerLineStyle: {
                color: string;
            };
        };
        y: {
            label: {
                color: string;
            };
            itemStyle: {
                borderColor: string;
            };
            dividerLineStyle: {
                color: string;
            };
        };
        backgroundColor: {
            borderColor: string;
        };
        body: {
            itemStyle: {
                borderColor: string;
            };
        };
    };
    timeAxis: {
        axisLine: {
            lineStyle: {
                color: string;
            };
        };
        splitLine: {
            lineStyle: {
                color: string;
            };
        };
        splitArea: {
            areaStyle: {
                color: string[];
            };
        };
        minorSplitLine: {
            lineStyle: {
                color: string;
            };
        };
        axisLabel: {
            color: string;
        };
        axisName: {};
    };
    logAxis: {
        axisLine: {
            lineStyle: {
                color: string;
            };
        };
        splitLine: {
            lineStyle: {
                color: string;
            };
        };
        splitArea: {
            areaStyle: {
                color: string[];
            };
        };
        minorSplitLine: {
            lineStyle: {
                color: string;
            };
        };
        axisLabel: {
            color: string;
        };
        axisName: {};
    };
    valueAxis: {
        axisLine: {
            lineStyle: {
                color: string;
            };
        };
        splitLine: {
            lineStyle: {
                color: string;
            };
        };
        splitArea: {
            areaStyle: {
                color: string[];
            };
        };
        minorSplitLine: {
            lineStyle: {
                color: string;
            };
        };
        axisLabel: {
            color: string;
        };
        axisName: {};
    };
    categoryAxis: {
        axisLine: {
            lineStyle: {
                color: string;
            };
        };
        splitLine: {
            lineStyle: {
                color: string;
            };
        };
        splitArea: {
            areaStyle: {
                color: string[];
            };
        };
        minorSplitLine: {
            lineStyle: {
                color: string;
            };
        };
        axisLabel: {
            color: string;
        };
        axisName: {};
    };
    line: {
        symbol: string;
    };
    graph: {
        color: string[];
    };
    gauge: {
        title: {
            color: string;
        };
        axisLine: {
            lineStyle: {
                color: (string | number)[][];
            };
        };
        axisLabel: {
            color: string;
        };
        detail: {
            color: string;
        };
    };
    candlestick: {
        itemStyle: {
            color: string;
            color0: string;
            borderColor: string;
            borderColor0: string;
        };
    };
    funnel: {
        itemStyle: {
            borderColor: string;
        };
    };
    radar: {
        axisLine: {
            lineStyle: {
                color: string;
            };
        };
        splitLine: {
            lineStyle: {
                color: string;
            };
        };
        splitArea: {
            areaStyle: {
                color: string[];
            };
        };
        minorSplitLine: {
            lineStyle: {
                color: string;
            };
        };
        axisLabel: {
            color: string;
        };
        axisName: {};
    };
    treemap: {
        breadcrumb: {
            itemStyle: {
                color: string;
                textStyle: {
                    color: string;
                };
            };
            emphasis: {
                itemStyle: {
                    color: string;
                };
            };
        };
    };
    sunburst: {
        itemStyle: {
            borderColor: string;
        };
    };
    map: {
        itemStyle: {
            borderColor: string;
            areaColor: string;
        };
        label: {
            color: string;
        };
        emphasis: {
            label: {
                color: string;
            };
            itemStyle: {
                areaColor: string;
            };
        };
        select: {
            label: {
                color: string;
            };
            itemStyle: {
                areaColor: string;
            };
        };
    };
    geo: {
        itemStyle: {
            borderColor: string;
            areaColor: string;
        };
        emphasis: {
            label: {
                color: string;
            };
            itemStyle: {
                areaColor: string;
            };
        };
        select: {
            label: {
                color: string;
            };
            itemStyle: {
                color: string;
            };
        };
    };
};
export default theme;
