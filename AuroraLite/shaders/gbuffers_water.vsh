#version 120

varying vec2 texcoord;
varying vec2 lmcoord;
varying vec4 vertColor;
varying vec3 viewNormal;

void main() {
    gl_Position = ftransform();
    texcoord = gl_MultiTexCoord0.st;
    lmcoord = gl_MultiTexCoord1.st / 240.0;
    vertColor = gl_Color;
    viewNormal = normalize(gl_NormalMatrix * gl_Normal);
}
