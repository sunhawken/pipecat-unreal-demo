#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"

#include "PipecatJiggleComponent.generated.h"

class USkeletalMeshComponent;

// Secondary-motion ("jiggle") physics for the avatar's breasts and glutes.
//
// Each of the four jiggle bones (jiggle_breast_l/r, jiggle_glute_l/r) is a damped spring that follows where the
// template's animation puts the bone. The spring is solved every frame, AFTER the animation is evaluated, in fixed
// substeps (so it behaves the same at any frame rate), per axis of the mesh (X = side to side, Y = front to back,
// Z = up and down), with a smooth limit on how far it can travel. The result is added to the bone's position, which
// moves the skin that is weighted to it.
//
// Live tuning from the console (backtick): pipecat.Jiggle.Enable, .Gain, .Debug and, per region,
//   pipecat.Jiggle.Breast.Freq / .Damping / .MaxCm   and   pipecat.Jiggle.Glute.Freq / .Damping / .MaxCm
// Freq is the spring's natural frequency in Hz (higher = tighter), Damping is the damping ratio (0 = never stops,
// 1 = no overshoot), MaxCm is the largest travel in centimetres. -PipecatNoJiggle turns it off at start.
UCLASS(ClassGroup = (Pipecat))
class UPipecatJiggleComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;

	// The offset (component space, cm, gain applied) last added to a jiggle bone. The VR body is a separate poseable
	// mesh that copies the animation, so it re-applies these itself.
	bool GetAppliedOffset(FName BoneName, FVector& OutOffset) const;

private:
	struct FJiggleBone
	{
		FName Name;
		int32 Index = INDEX_NONE;
		bool bBreast = true;
		bool bInitialised = false;
		FVector PrevTarget = FVector::ZeroVector;   // where the animation had the bone last frame (world)
		FVector Pos = FVector::ZeroVector;          // the simulated particle (world)
		FVector Vel = FVector::ZeroVector;          // its velocity (world)
		FVector LastOffset = FVector::ZeroVector;   // what was applied last frame (component space, cm)
		float PeakCm = 0.0f;
		double DbgDt = 0.0, DbgTVy = 0.0, DbgVy = 0.0, DbgOffY = 0.0; int32 DbgN = 0;   // pipecat.Jiggle.Debug statistics                        // largest offset since the last debug print
	};

	void OnBonesFinalized();
	void Step(FJiggleBone& Bone, const FTransform& CompToWorld, FVector Target, float DeltaSeconds);

	UPROPERTY()
	TObjectPtr<USkeletalMeshComponent> Body;

	TArray<FJiggleBone> Bones;
	FDelegateHandle FinalizedHandle;
	float DebugTimer = 0.0f;
	double LastSimTime = -1.0;   // game time of the previous pose update
};
