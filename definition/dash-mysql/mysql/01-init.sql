USE agricultura;
CREATE TABLE mediciones (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    fecha DATETIME NOT NULL,
    tempMin DOUBLE NOT NULL,
    tempMax DOUBLE NOT NULL,
    tempAvg DOUBLE NOT NULL,
    humRelMin DOUBLE NOT NULL,
    humRelMax DOUBLE NOT NULL,
    humRelAvg DOUBLE NOT NULL,
    radSol DOUBLE NOT NULL COMMENT 'Radiacion solar media del periodo, W/m2',
    prec DOUBLE NOT NULL COMMENT 'Precipitacion acumulada del periodo, mm',
    INDEX idx_fecha (fecha)
);

-- Datos ficticios: resumen por hora.
INSERT INTO mediciones
(fecha,tempMin,tempMax,tempAvg,humRelMin,humRelMax,humRelAvg,radSol,prec)
VALUES
(NOW() - INTERVAL 5 HOUR,21,25,23,45,60,52,100,0),
(NOW() - INTERVAL 4 HOUR,23,28,25.5,40,55,47,250,0),
(NOW() - INTERVAL 3 HOUR,26,31,28.5,35,49,42,450,0),
(NOW() - INTERVAL 2 HOUR,28,34,31,30,44,37,650,0),
(NOW() - INTERVAL 1 HOUR,27,32,29.5,40,58,49,350,1.5),
(NOW(),25,29,27,55,72,63,150,3);
